"""
Concurrency regression test for the stock-out race condition fix.

Simulates two threads simultaneously trying to stock-out from the same
InventoryItem row, where only ONE of them should actually have enough
stock to succeed. Before the fix (Python read-modify-write), both
requests could read the same starting quantity and both pass
validation, resulting in an oversell (negative or incorrect final
quantity). After the fix (atomic conditional SQL UPDATE), exactly one
request succeeds and the other is correctly rejected.
"""
import threading

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401
from app.schemas.product import ProductCreate
from app.schemas.warehouse import WarehouseCreate, LocationCreate
from app.schemas.inventory import StockInRequest, StockOutRequest
from app.services.product_service import ProductService
from app.services.warehouse_service import WarehouseService
from app.services.inventory_service import InventoryService, InventoryServiceError


def test_concurrent_stock_out_does_not_oversell():
    # Use a file-backed (not pure in-memory) SQLite DB so multiple
    # threads with their OWN sessions can all see committed writes —
    # a single in-memory :memory: DB is only visible to one connection.
    import tempfile
    import os

    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    setup_session = TestSession()
    try:
        product = ProductService(setup_session).create_product(
            ProductCreate(product_code="RACE-001", name="Race Test Item", price=1, reorder_level=1),
            user_id=1,
        )
        warehouse = WarehouseService(setup_session).create_warehouse(WarehouseCreate(name="Race WH"), 1)
        location = WarehouseService(setup_session).create_location(
            LocationCreate(warehouse_id=warehouse.id, zone="A"), 1
        )
        # Exactly 10 units in stock — two threads will each try to take out 8.
        # At most ONE can succeed; both succeeding would mean quantity went to -6.
        InventoryService(setup_session).stock_in(
            StockInRequest(product_id=product.id, location_id=location.id, quantity=10), user_id=1
        )
        product_id, location_id = product.id, location.id
    finally:
        setup_session.close()

    results = {}

    def attempt_stock_out(thread_name: str):
        session = TestSession()
        try:
            service = InventoryService(session)
            try:
                service.stock_out(
                    StockOutRequest(product_id=product_id, location_id=location_id, quantity=8),
                    user_id=1,
                )
                results[thread_name] = "success"
            except InventoryServiceError:
                results[thread_name] = "rejected"
        finally:
            session.close()

    t1 = threading.Thread(target=attempt_stock_out, args=("t1",))
    t2 = threading.Thread(target=attempt_stock_out, args=("t2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    outcomes = list(results.values())
    assert outcomes.count("success") == 1, (
        f"Expected exactly one thread to succeed, got: {results}. "
        "If both succeeded, the race condition has regressed and stock was oversold."
    )
    assert outcomes.count("rejected") == 1

    # Final quantity must reflect exactly one successful stock-out (10 - 8 = 2), never negative.
    verify_session = TestSession()
    try:
        final_item = InventoryService(verify_session).get_inventory_for_product(product_id)[0]
        assert final_item.quantity == 2, f"Expected final quantity 2, got {final_item.quantity}"
    finally:
        verify_session.close()

    os.remove(db_path)

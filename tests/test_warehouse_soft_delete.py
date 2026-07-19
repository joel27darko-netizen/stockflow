import pytest

from app.schemas.warehouse import WarehouseCreate, LocationCreate
from app.schemas.product import ProductCreate
from app.schemas.inventory import StockInRequest
from app.services.warehouse_service import WarehouseService, WarehouseServiceError
from app.services.product_service import ProductService
from app.services.inventory_service import InventoryService


def test_deactivate_warehouse_hides_it_from_default_listing(db_session):
    service = WarehouseService(db_session)
    warehouse = service.create_warehouse(WarehouseCreate(name="Test WH"), 1)

    service.deactivate_warehouse(warehouse.id, 1)

    active = service.list_warehouses()
    all_including_inactive = service.list_warehouses(include_inactive=True)
    assert warehouse.id not in [w.id for w in active]
    assert warehouse.id in [w.id for w in all_including_inactive]


def test_reactivate_warehouse_restores_visibility(db_session):
    service = WarehouseService(db_session)
    warehouse = service.create_warehouse(WarehouseCreate(name="Test WH"), 1)
    service.deactivate_warehouse(warehouse.id, 1)
    service.reactivate_warehouse(warehouse.id, 1)

    active = service.list_warehouses()
    assert warehouse.id in [w.id for w in active]


def test_delete_warehouse_without_history_succeeds(db_session):
    service = WarehouseService(db_session)
    warehouse = service.create_warehouse(WarehouseCreate(name="Test WH"), 1)
    service.delete_warehouse(warehouse.id, 1)

    assert service.repo.get(warehouse.id) is None


def test_delete_warehouse_with_transaction_history_is_blocked(db_session):
    warehouse_service = WarehouseService(db_session)
    product_service = ProductService(db_session)
    inventory_service = InventoryService(db_session)

    warehouse = warehouse_service.create_warehouse(WarehouseCreate(name="Test WH"), 1)
    location = warehouse_service.create_location(LocationCreate(warehouse_id=warehouse.id, zone="A"), 1)
    product = product_service.create_product(ProductCreate(product_code="SKU-1", name="Widget", price=1, reorder_level=1), 1)
    inventory_service.stock_in(StockInRequest(product_id=product.id, location_id=location.id, quantity=10), 1)

    with pytest.raises(WarehouseServiceError, match="transaction history"):
        warehouse_service.delete_warehouse(warehouse.id, 1)

    # Warehouse should still exist since the delete was blocked
    assert warehouse_service.repo.get(warehouse.id) is not None


def test_deactivate_location_hides_it_from_default_listing(db_session):
    service = WarehouseService(db_session)
    warehouse = service.create_warehouse(WarehouseCreate(name="Test WH"), 1)
    location = service.create_location(LocationCreate(warehouse_id=warehouse.id, zone="A"), 1)

    service.deactivate_location(location.id, 1)

    active_locations = service.list_locations()
    assert location.id not in [l.id for l in active_locations]

    all_locations = service.list_locations(include_inactive=True)
    assert location.id in [l.id for l in all_locations]


def test_creating_warehouse_with_same_name_as_inactive_one_is_rejected(db_session):
    """
    Since `name` has a DB-level unique constraint, creating a duplicate
    of a DEACTIVATED warehouse's name must still be caught with a
    friendly error — not an unhandled IntegrityError.
    """
    service = WarehouseService(db_session)
    warehouse = service.create_warehouse(WarehouseCreate(name="Test WH"), 1)
    service.deactivate_warehouse(warehouse.id, 1)

    with pytest.raises(WarehouseServiceError, match="already exists"):
        service.create_warehouse(WarehouseCreate(name="Test WH"), 1)

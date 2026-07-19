import pytest

from app.schemas.product import ProductCreate
from app.schemas.warehouse import WarehouseCreate, LocationCreate
from app.schemas.inventory import StockInRequest, StockOutRequest, StockAdjustmentRequest
from app.services.product_service import ProductService
from app.services.warehouse_service import WarehouseService
from app.services.inventory_service import InventoryService, InventoryServiceError


@pytest.fixture()
def product_and_location(db_session):
    product = ProductService(db_session).create_product(
        ProductCreate(product_code="SKU-100", name="Widget", price=10, reorder_level=5), 1
    )
    wh_service = WarehouseService(db_session)
    warehouse = wh_service.create_warehouse(WarehouseCreate(name="Main WH"), 1)
    location = wh_service.create_location(
        LocationCreate(warehouse_id=warehouse.id, zone="Zone A"), 1
    )
    return product, location


def test_stock_in_increases_quantity(db_session, product_and_location):
    product, location = product_and_location
    service = InventoryService(db_session)
    txn = service.stock_in(
        StockInRequest(product_id=product.id, location_id=location.id, quantity=20), user_id=1
    )
    assert txn.quantity_after == 20

    items = service.get_inventory_for_product(product.id)
    assert items[0].quantity == 20


def test_stock_out_decreases_quantity(db_session, product_and_location):
    product, location = product_and_location
    service = InventoryService(db_session)
    service.stock_in(StockInRequest(product_id=product.id, location_id=location.id, quantity=20), 1)
    txn = service.stock_out(
        StockOutRequest(product_id=product.id, location_id=location.id, quantity=8), user_id=1
    )
    assert txn.quantity_after == 12


def test_stock_out_fails_when_insufficient(db_session, product_and_location):
    product, location = product_and_location
    service = InventoryService(db_session)
    service.stock_in(StockInRequest(product_id=product.id, location_id=location.id, quantity=5), 1)
    with pytest.raises(InventoryServiceError):
        service.stock_out(
            StockOutRequest(product_id=product.id, location_id=location.id, quantity=10), user_id=1
        )


def test_adjustment_sets_exact_quantity(db_session, product_and_location):
    product, location = product_and_location
    service = InventoryService(db_session)
    service.stock_in(StockInRequest(product_id=product.id, location_id=location.id, quantity=20), 1)
    txn = service.adjust_stock(
        StockAdjustmentRequest(product_id=product.id, location_id=location.id, new_quantity=15), user_id=1
    )
    assert txn.quantity_after == 15
    assert txn.quantity == 5  # abs delta


def test_transfer_moves_stock_between_locations(db_session, product_and_location):
    from app.schemas.warehouse import LocationCreate
    from app.schemas.inventory import TransferRequest

    product, location_a = product_and_location
    location_b = WarehouseService(db_session).create_location(
        LocationCreate(warehouse_id=location_a.warehouse_id, zone="B"), 1
    )
    service = InventoryService(db_session)
    service.stock_in(StockInRequest(product_id=product.id, location_id=location_a.id, quantity=20), 1)

    txn_out, txn_in = service.transfer_stock(
        TransferRequest(product_id=product.id, from_location_id=location_a.id,
                         to_location_id=location_b.id, quantity=8),
        user_id=1,
    )

    assert txn_out.quantity_after == 12
    assert txn_in.quantity_after == 8
    assert txn_out.reference == txn_in.reference  # linked pair share a reference

    items = {item.location_id: item.quantity for item in service.get_inventory_for_product(product.id)}
    assert items[location_a.id] == 12
    assert items[location_b.id] == 8


def test_transfer_fails_with_insufficient_stock_at_source(db_session, product_and_location):
    from app.schemas.warehouse import LocationCreate
    from app.schemas.inventory import TransferRequest

    product, location_a = product_and_location
    location_b = WarehouseService(db_session).create_location(
        LocationCreate(warehouse_id=location_a.warehouse_id, zone="B"), 1
    )
    service = InventoryService(db_session)
    service.stock_in(StockInRequest(product_id=product.id, location_id=location_a.id, quantity=5), 1)

    with pytest.raises(InventoryServiceError):
        service.transfer_stock(
            TransferRequest(product_id=product.id, from_location_id=location_a.id,
                             to_location_id=location_b.id, quantity=10),
            user_id=1,
        )

    # Source quantity must be untouched — a failed transfer should leave no partial effect
    items = {item.location_id: item.quantity for item in service.get_inventory_for_product(product.id)}
    assert items[location_a.id] == 5


def test_transfer_same_location_rejected_at_schema_level():
    from pydantic import ValidationError
    from app.schemas.inventory import TransferRequest

    with pytest.raises(ValidationError):
        TransferRequest(product_id=1, from_location_id=1, to_location_id=1, quantity=5)


def test_transfer_total_quantity_unchanged_across_locations(db_session, product_and_location):
    """A transfer moves stock between locations but must never change the total held anywhere."""
    from app.schemas.warehouse import LocationCreate
    from app.schemas.inventory import TransferRequest

    product, location_a = product_and_location
    location_b = WarehouseService(db_session).create_location(
        LocationCreate(warehouse_id=location_a.warehouse_id, zone="B"), 1
    )
    service = InventoryService(db_session)
    service.stock_in(StockInRequest(product_id=product.id, location_id=location_a.id, quantity=30), 1)

    total_before = sum(item.quantity for item in service.get_inventory_for_product(product.id))
    service.transfer_stock(
        TransferRequest(product_id=product.id, from_location_id=location_a.id,
                         to_location_id=location_b.id, quantity=12),
        user_id=1,
    )
    total_after = sum(item.quantity for item in service.get_inventory_for_product(product.id))

    assert total_before == total_after == 30


def test_low_stock_flag_after_stock_out(db_session, product_and_location):
    product, location = product_and_location
    service = InventoryService(db_session)
    service.stock_in(StockInRequest(product_id=product.id, location_id=location.id, quantity=10), 1)
    service.stock_out(StockOutRequest(product_id=product.id, location_id=location.id, quantity=8), 1)
    db_session.refresh(product)
    assert product.total_quantity == 2
    assert product.is_low_stock is True  # reorder_level=5

"""
Regression test for the low-stock search bug: low_stock_only must be
applied in SQL (via count/subquery), not as a Python-side filter after
the page has already been sliced with LIMIT/OFFSET — otherwise a
low-stock product outside the current page silently vanishes from
results with no indication anything was cut off.
"""
from app.schemas.product import ProductCreate
from app.schemas.warehouse import WarehouseCreate, LocationCreate
from app.schemas.inventory import StockInRequest
from app.services.product_service import ProductService
from app.services.warehouse_service import WarehouseService
from app.services.inventory_service import InventoryService


def _make_location(db_session):
    wh_service = WarehouseService(db_session)
    warehouse = wh_service.create_warehouse(WarehouseCreate(name="Test WH"), 1)
    return wh_service.create_location(LocationCreate(warehouse_id=warehouse.id, zone="A"), 1)


def test_low_stock_search_finds_products_beyond_first_page(db_session):
    product_service = ProductService(db_session)
    inventory_service = InventoryService(db_session)
    location = _make_location(db_session)

    # 30 products with healthy stock (well above their reorder level) —
    # these sort before "ZZZ-LOWSTOCK" alphabetically by product_code.
    for i in range(30):
        product = product_service.create_product(
            ProductCreate(product_code=f"OK-{i:03d}", name=f"Healthy Item {i}", price=1, reorder_level=5),
            user_id=1,
        )
        inventory_service.stock_in(
            StockInRequest(product_id=product.id, location_id=location.id, quantity=100), user_id=1
        )

    # One low-stock product (zero quantity) that sorts onto a later page
    # under the old (buggy) Python-side-filter-after-LIMIT implementation.
    product_service.create_product(
        ProductCreate(product_code="ZZZ-LOWSTOCK", name="Low Stock Item", price=1, reorder_level=5),
        user_id=1,
    )

    # page_size smaller than the number of healthy products, so the
    # low-stock item would fall outside page 1 if SQL didn't filter first.
    result = product_service.search_products(low_stock_only=True, page=1, page_size=10)

    codes = [p.product_code for p in result.products]
    assert codes == ["ZZZ-LOWSTOCK"], (
        "Low-stock filtering did not correctly isolate only the low-stock product — "
        "this indicates a regression to Python-side filtering after LIMIT/OFFSET."
    )
    assert result.total == 1


def test_search_pagination_reports_accurate_total(db_session):
    service = ProductService(db_session)
    for i in range(15):
        service.create_product(
            ProductCreate(product_code=f"SKU-{i:03d}", name=f"Item {i}", price=1, reorder_level=1),
            user_id=1,
        )

    result = service.search_products(page=1, page_size=10)
    assert result.total == 15
    assert len(result.products) == 10
    assert result.total_pages == 2
    assert result.has_next is True
    assert result.has_previous is False

    result_page_2 = service.search_products(page=2, page_size=10)
    assert len(result_page_2.products) == 5
    assert result_page_2.has_next is False
    assert result_page_2.has_previous is True

import pytest

from app.schemas.product import ProductCreate, ProductUpdate, CategoryCreate
from app.services.product_service import ProductService, ProductServiceError


def test_create_product_generates_codes(db_session):
    service = ProductService(db_session)
    product = service.create_product(
        ProductCreate(product_code="sku-001", name="Widget", price=9.99, reorder_level=5),
        user_id=1,
    )
    assert product.product_code == "SKU-001"  # normalized to uppercase
    assert product.qr_code_path is not None
    assert product.barcode_path is not None
    assert product.barcode_value == "SKU-001"


def test_duplicate_product_code_rejected(db_session):
    service = ProductService(db_session)
    service.create_product(ProductCreate(product_code="SKU-001", name="Widget", price=1, reorder_level=1), 1)
    with pytest.raises(ProductServiceError):
        service.create_product(ProductCreate(product_code="SKU-001", name="Other", price=2, reorder_level=1), 1)


def test_update_product(db_session):
    service = ProductService(db_session)
    product = service.create_product(ProductCreate(product_code="SKU-002", name="Widget", price=1, reorder_level=1), 1)
    updated = service.update_product(product.id, ProductUpdate(price=25.5), 1)
    assert updated.price == 25.5


def test_delete_product(db_session):
    service = ProductService(db_session)
    product = service.create_product(ProductCreate(product_code="SKU-003", name="Widget", price=1, reorder_level=1), 1)
    service.delete_product(product.id, 1)
    assert service.get_product(product.id) is None


def test_category_uniqueness(db_session):
    service = ProductService(db_session)
    service.create_category(CategoryCreate(name="Electronics"), 1)
    with pytest.raises(ProductServiceError):
        service.create_category(CategoryCreate(name="Electronics"), 1)


def test_low_stock_detection(db_session):
    service = ProductService(db_session)
    product = service.create_product(
        ProductCreate(product_code="SKU-004", name="Widget", price=1, reorder_level=10), 1
    )
    assert product.is_low_stock is True  # zero quantity, reorder level 10


def test_blank_product_code_is_auto_generated(db_session):
    service = ProductService(db_session)
    product = service.create_product(
        ProductCreate(product_code=None, name="Auto Widget", price=5, reorder_level=5), 1
    )
    assert product.product_code is not None
    assert product.product_code.startswith("SKU-")


def test_empty_string_product_code_is_treated_as_auto_generate(db_session):
    """An empty/whitespace-only code from a form submission should behave
    identically to omitting product_code entirely."""
    service = ProductService(db_session)
    product = service.create_product(
        ProductCreate(product_code="   ", name="Auto Widget 2", price=5, reorder_level=5), 1
    )
    assert product.product_code.startswith("SKU-")


def test_auto_generated_codes_are_unique_across_multiple_products(db_session):
    service = ProductService(db_session)
    products = [
        service.create_product(ProductCreate(product_code=None, name=f"Item {i}", price=1, reorder_level=1), 1)
        for i in range(5)
    ]
    codes = [p.product_code for p in products]
    assert len(codes) == len(set(codes)), f"Expected all unique codes, got: {codes}"


def test_auto_generated_code_does_not_collide_with_existing_manual_code(db_session):
    """If a manually-entered code already occupies the next auto-generated
    slot, generation should skip past it rather than colliding."""
    service = ProductService(db_session)
    # Manually claim what would otherwise be the first auto-generated code
    manual = service.create_product(
        ProductCreate(product_code="SKU-00001", name="Manually Coded", price=1, reorder_level=1), 1
    )
    assert manual.product_code == "SKU-00001"

    auto = service.create_product(
        ProductCreate(product_code=None, name="Auto After Manual", price=1, reorder_level=1), 1
    )
    assert auto.product_code != "SKU-00001"
    assert auto.product_code.startswith("SKU-")


def test_manual_product_code_still_required_to_be_unique(db_session):
    service = ProductService(db_session)
    service.create_product(ProductCreate(product_code="SKU-999", name="First", price=1, reorder_level=1), 1)
    with pytest.raises(ProductServiceError):
        service.create_product(ProductCreate(product_code="SKU-999", name="Duplicate", price=1, reorder_level=1), 1)

import io

import pytest
from PIL import Image

from app.schemas.product import ProductCreate
from app.services.product_service import ProductService, ProductServiceError


def _make_test_image_bytes(fmt="JPEG", size=(200, 200)) -> bytes:
    img = Image.new("RGB", size, color=(120, 180, 220))
    buffer = io.BytesIO()
    img.save(buffer, format=fmt)
    return buffer.getvalue()


def test_upload_valid_image_sets_image_path(db_session):
    service = ProductService(db_session)
    product = service.create_product(ProductCreate(product_code="SKU-1", name="Widget", price=1, reorder_level=1), 1)

    updated = service.set_product_image(product.id, _make_test_image_bytes(), "image/jpeg", 1)

    assert updated.image_path is not None
    assert "SKU-1" in updated.image_path


def test_upload_rejects_non_image_bytes(db_session):
    service = ProductService(db_session)
    product = service.create_product(ProductCreate(product_code="SKU-1", name="Widget", price=1, reorder_level=1), 1)

    with pytest.raises(ProductServiceError, match="valid image"):
        service.set_product_image(product.id, b"this is not an image, just text", "image/jpeg", 1)


def test_upload_rejects_oversized_file(db_session):
    service = ProductService(db_session)
    product = service.create_product(ProductCreate(product_code="SKU-1", name="Widget", price=1, reorder_level=1), 1)

    oversized = b"\x00" * (6 * 1024 * 1024)  # 6MB of junk, over the 5MB limit
    with pytest.raises(ProductServiceError):
        service.set_product_image(product.id, oversized, "image/jpeg", 1)


def test_upload_resizes_large_image(db_session):
    service = ProductService(db_session)
    product = service.create_product(ProductCreate(product_code="SKU-1", name="Widget", price=1, reorder_level=1), 1)

    large_image = _make_test_image_bytes(size=(2000, 1500))
    updated = service.set_product_image(product.id, large_image, "image/jpeg", 1)

    saved_path = "app" + updated.image_path  # e.g. /static/product_images/SKU-1.jpg
    with Image.open(saved_path) as img:
        assert max(img.size) <= 800


def test_remove_product_image_clears_path(db_session):
    service = ProductService(db_session)
    product = service.create_product(ProductCreate(product_code="SKU-1", name="Widget", price=1, reorder_level=1), 1)
    service.set_product_image(product.id, _make_test_image_bytes(), "image/jpeg", 1)

    updated = service.remove_product_image(product.id, 1)
    assert updated.image_path is None


def test_reupload_replaces_previous_image(db_session):
    service = ProductService(db_session)
    product = service.create_product(ProductCreate(product_code="SKU-1", name="Widget", price=1, reorder_level=1), 1)

    first = service.set_product_image(product.id, _make_test_image_bytes(size=(100, 100)), "image/jpeg", 1)
    second = service.set_product_image(product.id, _make_test_image_bytes(size=(300, 300)), "image/jpeg", 1)

    # Same product code -> same filename -> path is stable across re-uploads
    assert first.image_path == second.image_path

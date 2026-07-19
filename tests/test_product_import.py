import io

import openpyxl
import pytest

from app.services.product_import_service import ProductImportService, BulkImportError


def _csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def test_import_valid_csv_creates_products(db_session):
    service = ProductImportService(db_session)
    csv_content = (
        "product_code,name,description,category,price,reorder_level\n"
        "SKU-1,Widget A,A test widget,Electronics,9.99,10\n"
        "SKU-2,Widget B,,Electronics,4.50,5\n"
    )
    result = service.import_file(_csv_bytes(csv_content), "products.csv", user_id=1)

    assert result.total_rows == 2
    assert result.created_count == 2
    assert result.error_count == 0

    created = service.product_repo.get_by_code("SKU-1")
    assert created is not None
    assert created.name == "Widget A"
    assert created.category.name == "Electronics"


def test_import_reuses_existing_category_by_name(db_session):
    service = ProductImportService(db_session)
    csv_content = (
        "product_code,name,category,price\n"
        "SKU-1,Widget A,Electronics,9.99\n"
        "SKU-2,Widget B,Electronics,4.50\n"
    )
    service.import_file(_csv_bytes(csv_content), "products.csv", user_id=1)

    categories = service.category_repo.list_all()
    electronics_categories = [c for c in categories if c.name == "Electronics"]
    assert len(electronics_categories) == 1  # not duplicated across two rows


def test_import_isolates_bad_rows_without_failing_whole_batch(db_session):
    service = ProductImportService(db_session)
    csv_content = (
        "product_code,name,price\n"
        "SKU-1,Good Widget,9.99\n"
        "SKU-2,Bad Price Widget,not-a-number\n"
        "SKU-3,,5.00\n"
        "SKU-4,Good Widget Two,15.00\n"
    )
    result = service.import_file(_csv_bytes(csv_content), "products.csv", user_id=1)

    assert result.total_rows == 4
    assert result.created_count == 2
    assert result.error_count == 2
    assert service.product_repo.get_by_code("SKU-1") is not None
    assert service.product_repo.get_by_code("SKU-4") is not None
    assert service.product_repo.get_by_code("SKU-2") is None


def test_import_rejects_duplicate_code_within_same_file(db_session):
    service = ProductImportService(db_session)
    csv_content = (
        "product_code,name,price\n"
        "SKU-1,First,9.99\n"
        "SKU-1,Duplicate,5.00\n"
    )
    result = service.import_file(_csv_bytes(csv_content), "products.csv", user_id=1)

    assert result.created_count == 1
    assert result.error_count == 1
    assert "Duplicate" in result.errors[0].message or "duplicate" in result.errors[0].message.lower()


def test_import_rejects_code_that_already_exists_in_db(db_session):
    service = ProductImportService(db_session)
    service.import_file(_csv_bytes("product_code,name,price\nSKU-1,First,9.99\n"), "a.csv", user_id=1)
    result = service.import_file(_csv_bytes("product_code,name,price\nSKU-1,Second,5.00\n"), "b.csv", user_id=1)

    assert result.created_count == 0
    assert result.error_count == 1
    assert "already exists" in result.errors[0].message


def test_import_missing_required_column_raises_file_level_error(db_session):
    service = ProductImportService(db_session)
    csv_content = "name\nWidget\n"  # missing price, which is still required
    with pytest.raises(BulkImportError, match="price"):
        service.import_file(_csv_bytes(csv_content), "products.csv", user_id=1)


def test_import_empty_file_raises_error(db_session):
    service = ProductImportService(db_session)
    with pytest.raises(BulkImportError):
        service.import_file(b"", "products.csv", user_id=1)


def test_import_unsupported_extension_raises_error(db_session):
    service = ProductImportService(db_session)
    with pytest.raises(BulkImportError, match="Unsupported file type"):
        service.import_file(b"whatever", "products.txt", user_id=1)


def test_import_valid_xlsx_creates_products(db_session):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["product_code", "name", "description", "category", "price", "reorder_level"])
    sheet.append(["SKU-X1", "Excel Widget", "From Excel", "Hardware", 12.5, 8])

    buffer = io.BytesIO()
    workbook.save(buffer)
    file_bytes = buffer.getvalue()

    service = ProductImportService(db_session)
    result = service.import_file(file_bytes, "products.xlsx", user_id=1)

    assert result.created_count == 1
    assert result.error_count == 0
    product = service.product_repo.get_by_code("SKU-X1")
    assert product is not None
    assert product.category.name == "Hardware"


def test_import_column_aliases_are_recognized(db_session):
    """Headers like 'SKU' and 'Product Name' should map to the canonical fields."""
    service = ProductImportService(db_session)
    csv_content = "SKU,Product Name,Category Name,price\nSKU-A,Aliased Widget,Tools,3.25\n"
    result = service.import_file(_csv_bytes(csv_content), "products.csv", user_id=1)

    assert result.created_count == 1
    product = service.product_repo.get_by_code("SKU-A")
    assert product.name == "Aliased Widget"
    assert product.category.name == "Tools"


def test_import_blank_product_code_auto_generates(db_session):
    service = ProductImportService(db_session)
    csv_content = "product_code,name,price\n,Auto Generated Item,9.99\n"
    result = service.import_file(_csv_bytes(csv_content), "products.csv", user_id=1)

    assert result.created_count == 1
    assert result.error_count == 0
    assert "(auto-generated)" in result.row_results[0].product_code


def test_import_multiple_blank_codes_all_get_unique_codes(db_session):
    service = ProductImportService(db_session)
    csv_content = (
        "product_code,name,price\n"
        ",First Auto,1.00\n"
        ",Second Auto,2.00\n"
        ",Third Auto,3.00\n"
    )
    result = service.import_file(_csv_bytes(csv_content), "products.csv", user_id=1)

    assert result.created_count == 3
    assert result.error_count == 0

    all_products = service.product_repo.get_all_with_relations()
    codes = [p.product_code for p in all_products]
    assert len(codes) == len(set(codes)), f"Expected unique codes, got: {codes}"


def test_import_product_code_column_entirely_absent_still_works(db_session):
    """product_code is no longer a required column at all — a file
    without that column header should auto-generate for every row."""
    service = ProductImportService(db_session)
    csv_content = "name,price\nNo Code Column Item,9.99\n"
    result = service.import_file(_csv_bytes(csv_content), "products.csv", user_id=1)

    assert result.created_count == 1
    assert result.error_count == 0


def test_import_mixes_manual_and_auto_generated_codes(db_session):
    service = ProductImportService(db_session)
    csv_content = (
        "product_code,name,price\n"
        "MANUAL-1,Manually Coded,5.00\n"
        ",Auto Coded,6.00\n"
    )
    result = service.import_file(_csv_bytes(csv_content), "products.csv", user_id=1)

    assert result.created_count == 2
    assert service.product_repo.get_by_code("MANUAL-1") is not None

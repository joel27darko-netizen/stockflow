"""
Bulk product import from CSV or Excel (.xlsx).

Design choices worth knowing:
  - Each row is processed independently: one bad row (bad price, missing
    name, duplicate code) does NOT abort the whole batch. We collect a
    per-row outcome (created / skipped / error) and show the user a
    complete report, so a 200-row import doesn't fail entirely because
    row 143 had a typo.
  - Categories referenced by name are auto-created if they don't exist
    yet — this is a deliberate convenience for bulk-loading data from an
    external system that doesn't know about StockFlow's category IDs.
  - Column headers are matched case-insensitively and with whitespace
    stripped, so "Product Code", "product_code", and " PRODUCT_CODE "
    all resolve to the same field.
"""
import csv
import io
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

import openpyxl
from sqlalchemy.orm import Session

from app.repositories.product_repository import ProductRepository, CategoryRepository
from app.schemas.product import ProductCreate
from app.services.audit_service import AuditService
from app.services.code_generator_service import CodeGeneratorService
from app.models.product import Product, Category

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"name", "price"}
KNOWN_COLUMNS = {"product_code", "name", "description", "category", "price", "reorder_level"}

# Normalizes a handful of likely header spellings to our canonical field names.
COLUMN_ALIASES = {
    "code": "product_code",
    "sku": "product_code",
    "product code": "product_code",
    "product name": "name",
    "category name": "category",
    "category_name": "category",
    "reorder level": "reorder_level",
    "reorder point": "reorder_level",
}


class BulkImportError(Exception):
    """Raised for file-level problems (bad format, unreadable file) — not per-row issues."""
    pass


@dataclass
class RowResult:
    row_number: int
    product_code: str
    status: str  # "created" | "error"
    message: str = ""


@dataclass
class BulkImportResult:
    total_rows: int
    created_count: int
    error_count: int
    row_results: List[RowResult] = field(default_factory=list)

    @property
    def errors(self) -> List[RowResult]:
        return [r for r in self.row_results if r.status == "error"]


class ProductImportService:
    def __init__(self, db: Session):
        self.db = db
        self.product_repo = ProductRepository(db)
        self.category_repo = CategoryRepository(db)
        self.audit = AuditService(db)
        self._category_cache: Dict[str, Category] = {}

    def _normalize_header(self, header: str) -> str:
        key = header.strip().lower()
        return COLUMN_ALIASES.get(key, key)

    def _parse_csv(self, file_bytes: bytes) -> List[Dict[str, Any]]:
        try:
            text = file_bytes.decode("utf-8-sig")  # handles Excel-exported CSVs with a BOM
        except UnicodeDecodeError:
            raise BulkImportError("Could not read this file as text. Please save it as UTF-8 CSV and try again.")

        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            raise BulkImportError("The file is empty.")

        headers = [self._normalize_header(h) for h in rows[0]]
        return self._rows_to_dicts(headers, rows[1:])

    def _parse_xlsx(self, file_bytes: bytes) -> List[Dict[str, Any]]:
        try:
            workbook = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        except Exception as exc:
            raise BulkImportError(f"Could not read this Excel file — it may be corrupted or not a valid .xlsx: {exc}")

        sheet = workbook.active
        all_rows = list(sheet.iter_rows(values_only=True))
        if not all_rows:
            raise BulkImportError("The spreadsheet is empty.")

        headers = [self._normalize_header(str(h) if h is not None else "") for h in all_rows[0]]
        data_rows = [[("" if cell is None else cell) for cell in row] for row in all_rows[1:]]
        return self._rows_to_dicts(headers, data_rows)

    def _rows_to_dicts(self, headers: List[str], data_rows: List[List[Any]]) -> List[Dict[str, Any]]:
        missing = REQUIRED_COLUMNS - set(headers)
        if missing:
            raise BulkImportError(
                f"Missing required column(s): {', '.join(sorted(missing))}. "
                f"Expected columns include: {', '.join(sorted(KNOWN_COLUMNS))}."
            )

        result = []
        for row in data_rows:
            if not any(str(cell).strip() for cell in row):
                continue  # skip fully blank rows
            row_dict = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
            result.append(row_dict)
        return result

    def _get_or_create_category(self, name: str, user_id: int) -> Optional[Category]:
        name = (name or "").strip()
        if not name:
            return None
        if name in self._category_cache:
            return self._category_cache[name]
        category = self.category_repo.get_by_name(name)
        if not category:
            category = self.category_repo.create(Category(name=name))
            self.audit.log(user_id, "CREATE_CATEGORY", "Category", category.id, f"{name} (via bulk import)")
        self._category_cache[name] = category
        return category

    def _generate_unique_product_code(self, seen_codes_this_file: set, next_attempt: int) -> tuple:
        """
        Same auto-generation scheme as ProductService (SKU-00001, ...),
        reimplemented here rather than shared, since this class works
        directly against the repository rather than through
        ProductService. `next_attempt` is threaded through the caller's
        row loop so multiple blank-code rows in the same file each get
        a different generated code, without re-querying the DB count
        for every single row.
        """
        attempt = next_attempt
        for _ in range(10_000):
            candidate = f"SKU-{attempt:05d}"
            attempt += 1
            if candidate in seen_codes_this_file:
                continue
            if self.product_repo.get_by_code(candidate):
                continue
            return candidate, attempt
        raise ValueError("Could not auto-generate a unique product code for this row.")

    def import_file(self, file_bytes: bytes, filename: str, user_id: int) -> BulkImportResult:
        lower_name = filename.lower()
        if lower_name.endswith(".csv"):
            rows = self._parse_csv(file_bytes)
        elif lower_name.endswith(".xlsx"):
            rows = self._parse_xlsx(file_bytes)
        else:
            raise BulkImportError("Unsupported file type. Please upload a .csv or .xlsx file.")

        if not rows:
            raise BulkImportError("No data rows found in the file (only a header row, or the file is empty).")

        row_results: List[RowResult] = []
        created_count = 0

        # Track codes seen within this file to catch in-file duplicates
        # (e.g. two rows with the same product_code) separately from
        # codes that already exist in the database.
        seen_codes_this_file = set()
        # Starting point for auto-generated codes in this batch — advances
        # each time a blank product_code cell needs one, so multiple blank
        # rows don't collide with each other.
        next_auto_attempt = self.product_repo.count() + 1

        for i, row in enumerate(rows, start=2):  # row 2 = first data row (row 1 is the header)
            raw_code = str(row.get("product_code", "")).strip()
            code = raw_code.upper()
            was_auto_generated = False

            try:
                if not code:
                    code, next_auto_attempt = self._generate_unique_product_code(
                        seen_codes_this_file, next_auto_attempt
                    )
                    was_auto_generated = True
                elif code in seen_codes_this_file:
                    raise ValueError(f"Duplicate product_code '{code}' appears more than once in this file.")
                elif self.product_repo.get_by_code(code):
                    raise ValueError(f"Product code '{code}' already exists in StockFlow — skipped.")

                name = str(row.get("name", "")).strip()
                if not name:
                    raise ValueError("name is required and was blank.")

                raw_price = row.get("price", "")
                try:
                    price = float(raw_price)
                    if price < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    raise ValueError(f"price '{raw_price}' is not a valid non-negative number.")

                raw_reorder = row.get("reorder_level", 10)
                try:
                    reorder_level = int(raw_reorder) if str(raw_reorder).strip() != "" else 10
                    if reorder_level < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    raise ValueError(f"reorder_level '{raw_reorder}' is not a valid non-negative whole number.")

                category = self._get_or_create_category(str(row.get("category", "")), user_id)

                product = Product(
                    product_code=code,
                    name=name,
                    description=str(row.get("description", "") or "").strip() or None,
                    category_id=category.id if category else None,
                    price=price,
                    reorder_level=reorder_level,
                )
                product = self.product_repo.create(product)

                # Best-effort label generation — a failure here shouldn't
                # fail the whole row, since the product record itself is valid.
                try:
                    qr_path = CodeGeneratorService.generate_qr_code(product.product_code)
                    barcode_path, barcode_value = CodeGeneratorService.generate_barcode(product.product_code)
                    product.qr_code_path = qr_path
                    product.barcode_path = barcode_path
                    product.barcode_value = barcode_value
                    self.product_repo.update(product)
                except Exception as exc:
                    logger.warning("Label generation failed during bulk import for %s: %s", code, exc)

                seen_codes_this_file.add(code)
                created_count += 1
                result_code = f"{code} (auto-generated)" if was_auto_generated else code
                row_results.append(RowResult(row_number=i, product_code=result_code, status="created"))

            except ValueError as e:
                row_results.append(RowResult(row_number=i, product_code=code or "(blank)", status="error", message=str(e)))
            except Exception as e:
                logger.exception("Unexpected error importing row %s", i)
                row_results.append(RowResult(row_number=i, product_code=code or "(blank)", status="error", message=f"Unexpected error: {e}"))

        self.audit.log(
            user_id, "BULK_IMPORT_PRODUCTS", "Product", None,
            f"file={filename}, created={created_count}, errors={len(rows) - created_count}",
        )
        logger.info("Bulk import complete: file=%s created=%s errors=%s", filename, created_count, len(rows) - created_count)

        return BulkImportResult(
            total_rows=len(rows),
            created_count=created_count,
            error_count=len(rows) - created_count,
            row_results=row_results,
        )

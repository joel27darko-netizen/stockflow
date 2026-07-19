import logging
from dataclasses import dataclass
from typing import Optional, List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.product import Product, Category
from app.repositories.product_repository import ProductRepository, CategoryRepository
from app.schemas.product import ProductCreate, ProductUpdate, CategoryCreate
from app.services.audit_service import AuditService
from app.services.code_generator_service import CodeGeneratorService
from app.services.product_image_service import ProductImageService, ImageUploadError

logger = logging.getLogger(__name__)


class ProductServiceError(Exception):
    pass


@dataclass
class ProductSearchResult:
    products: List[Product]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def start_index(self) -> int:
        """1-based index of the first item on this page, for 'Showing X-Y of Z'."""
        return 0 if self.total == 0 else (self.page - 1) * self.page_size + 1

    @property
    def end_index(self) -> int:
        return min(self.page * self.page_size, self.total)


class ProductService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProductRepository(db)
        self.category_repo = CategoryRepository(db)
        self.audit = AuditService(db)

    # ---------- Categories ----------
    def create_category(self, data: CategoryCreate, user_id: int) -> Category:
        if self.category_repo.get_by_name(data.name):
            raise ProductServiceError(f"A category named '{data.name}' already exists.")
        category = Category(name=data.name, description=data.description)
        category = self.category_repo.create(category)
        self.audit.log(user_id, "CREATE_CATEGORY", "Category", category.id, data.name)
        return category

    def list_categories(self) -> List[Category]:
        return self.category_repo.list_all()

    # ---------- Products ----------
    def _generate_unique_product_code(self) -> str:
        """
        Auto-generates a product code in the form SKU-00001, SKU-00002, ...
        Starts from (current product count + 1) and increments on
        collision — this naturally handles gaps left by deleted products
        and coexists safely with manually-entered codes that don't follow
        this pattern at all (a collision there just bumps to the next
        number, same as any other collision).
        """
        attempt = self.repo.count() + 1
        for _ in range(10_000):
            candidate = f"SKU-{attempt:05d}"
            if not self.repo.get_by_code(candidate):
                return candidate
            attempt += 1
        # Practically unreachable, but fail loudly rather than looping forever
        raise ProductServiceError(
            "Could not auto-generate a unique product code after many attempts. "
            "Please enter one manually."
        )

    def create_product(self, data: ProductCreate, user_id: int) -> Product:
        was_auto_generated = not data.product_code
        product_code = data.product_code or self._generate_unique_product_code()

        # Only check for a manual duplicate here — an auto-generated code
        # is already guaranteed unique by _generate_unique_product_code.
        if not was_auto_generated and self.repo.get_by_code(product_code):
            raise ProductServiceError(
                f"Product code '{product_code}' already exists. Choose a different code, "
                "or leave the field blank to auto-generate one."
            )

        product = Product(
            product_code=product_code,
            name=data.name,
            description=data.description,
            category_id=data.category_id,
            price=data.price,
            reorder_level=data.reorder_level,
        )
        product = self.repo.create(product)

        # Generate QR + barcode after we have a persisted product_code.
        # This is deliberately non-fatal: a product is still fully usable
        # without its label images, so we log the failure rather than
        # rolling back product creation over an image-generation glitch.
        try:
            qr_path = CodeGeneratorService.generate_qr_code(product.product_code)
            barcode_path, barcode_value = CodeGeneratorService.generate_barcode(product.product_code)
            product.qr_code_path = qr_path
            product.barcode_path = barcode_path
            product.barcode_value = barcode_value
            product = self.repo.update(product)
        except Exception as exc:
            logger.error("Failed generating codes for product %s: %s", product.product_code, exc)

        code_origin_note = " (auto-generated)" if was_auto_generated else " (manually entered)"
        self.audit.log(user_id, "CREATE_PRODUCT", "Product", product.id, product.product_code + code_origin_note)
        logger.info("Product created: %s%s", product.product_code, code_origin_note)
        return product

    def update_product(self, product_id: int, data: ProductUpdate, user_id: int) -> Product:
        product = self.repo.get(product_id)
        if not product:
            raise ProductServiceError("That product no longer exists — it may have been deleted by another user.")

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(product, field, value)

        product = self.repo.update(product)
        self.audit.log(user_id, "UPDATE_PRODUCT", "Product", product.id, str(data.model_dump(exclude_unset=True)))
        logger.info("Product updated: %s", product.product_code)
        return product

    def delete_product(self, product_id: int, user_id: int) -> None:
        product = self.repo.get(product_id)
        if not product:
            raise ProductServiceError("That product no longer exists — it may have already been deleted.")
        code = product.product_code
        image_path = product.image_path
        try:
            self.repo.delete(product)
        except IntegrityError:
            self.db.rollback()
            raise ProductServiceError(
                f"'{code}' cannot be deleted because it has transaction history. "
                "Mark it inactive instead to preserve the audit trail and hide it from active listings."
            )
        if image_path:
            ProductImageService.delete_image(image_path)
        self.audit.log(user_id, "DELETE_PRODUCT", "Product", product_id, code)
        logger.info("Product deleted: %s", code)

    def set_product_image(self, product_id: int, file_bytes: bytes, content_type: str, user_id: int) -> Product:
        """
        Validates and saves an uploaded photo for a product, replacing
        any previous image. Raises ProductServiceError (not
        ImageUploadError directly) so callers only need to catch one
        exception type from this service, consistent with every other
        product operation.
        """
        product = self.repo.get(product_id)
        if not product:
            raise ProductServiceError("That product no longer exists — it may have been deleted.")

        old_image_path = product.image_path
        try:
            new_path = ProductImageService.validate_and_save(product.product_code, file_bytes, content_type)
        except ImageUploadError as e:
            raise ProductServiceError(str(e))

        product.image_path = new_path
        product = self.repo.update(product)

        # Clean up the old file only after the new one is safely saved
        # and the DB row updated, so a mid-upload failure never leaves
        # the product without any image on disk.
        if old_image_path and old_image_path != new_path:
            ProductImageService.delete_image(old_image_path)

        self.audit.log(user_id, "UPDATE_PRODUCT_IMAGE", "Product", product.id, product.product_code)
        logger.info("Product image updated: %s", product.product_code)
        return product

    def remove_product_image(self, product_id: int, user_id: int) -> Product:
        product = self.repo.get(product_id)
        if not product:
            raise ProductServiceError("That product no longer exists — it may have been deleted.")
        if product.image_path:
            ProductImageService.delete_image(product.image_path)
            product.image_path = None
            product = self.repo.update(product)
            self.audit.log(user_id, "REMOVE_PRODUCT_IMAGE", "Product", product.id, product.product_code)
            logger.info("Product image removed: %s", product.product_code)
        return product

    def get_product(self, product_id: int) -> Optional[Product]:
        return self.repo.get(product_id)

    def get_by_code_or_barcode(self, code: str) -> Optional[Product]:
        """Used by the simulated scanner: resolves a scanned code to a product."""
        code = (code or "").strip()
        if not code:
            return None
        product = self.repo.get_by_code(code)
        if not product:
            product = self.repo.get_by_barcode(code)
        return product

    def search_products(
        self,
        query: Optional[str] = None,
        category_id: Optional[int] = None,
        low_stock_only: bool = False,
        page: int = 1,
        page_size: int = 25,
    ) -> ProductSearchResult:
        """
        Returns a page of matching products PLUS the true total count of
        all matching rows (not just what fits on this page), so the UI
        can show 'Showing 1-25 of 143' and render real pagination
        instead of silently cutting results off at an arbitrary limit.
        """
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        skip = (page - 1) * page_size

        total = self.repo.count_search(
            query=query, category_id=category_id, low_stock_only=low_stock_only
        )
        products = self.repo.search(
            query=query,
            category_id=category_id,
            low_stock_only=low_stock_only,
            skip=skip,
            limit=page_size,
        )
        return ProductSearchResult(products=products, total=total, page=page, page_size=page_size)

    def get_all_products(self) -> List[Product]:
        return self.repo.get_all_with_relations()

    def get_low_stock_products(self) -> List[Product]:
        return [p for p in self.repo.get_all_with_relations() if p.is_low_stock and p.is_active]

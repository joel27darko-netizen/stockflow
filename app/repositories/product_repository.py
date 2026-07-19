from typing import Optional, List

from sqlalchemy import or_, func
from sqlalchemy.orm import Session, joinedload

from app.models.product import Product, Category
from app.models.inventory import InventoryItem
from app.repositories.base import BaseRepository


class ProductRepository(BaseRepository[Product]):
    def __init__(self, db: Session):
        super().__init__(Product, db)

    def get_by_code(self, product_code: str) -> Optional[Product]:
        return (
            self.db.query(Product)
            .filter(Product.product_code == product_code.upper())
            .first()
        )

    def get_by_barcode(self, barcode_value: str) -> Optional[Product]:
        return self.db.query(Product).filter(Product.barcode_value == barcode_value).first()

    def _search_query(
        self,
        query: Optional[str] = None,
        category_id: Optional[int] = None,
        low_stock_only: bool = False,
        is_active: Optional[bool] = True,
    ):
        """
        Builds the filtered query shared by both `search()` and
        `count_search()`. IMPORTANT: low_stock_only is applied here, in
        SQL, via a subquery that sums quantity per product — NOT as a
        Python-side filter after the page has already been sliced with
        LIMIT/OFFSET. Filtering in Python after limiting in SQL would
        silently drop matching low-stock products that happen to fall
        outside the current page, with no indication to the user that
        results were incomplete.
        """
        q = self.db.query(Product).options(joinedload(Product.category))

        if is_active is not None:
            q = q.filter(Product.is_active == is_active)

        if query:
            like = f"%{query.strip()}%"
            q = q.filter(
                or_(
                    Product.name.ilike(like),
                    Product.product_code.ilike(like),
                    Product.description.ilike(like),
                )
            )

        if category_id:
            q = q.filter(Product.category_id == category_id)

        if low_stock_only:
            qty_subq = (
                self.db.query(
                    InventoryItem.product_id.label("product_id"),
                    func.coalesce(func.sum(InventoryItem.quantity), 0).label("total_qty"),
                )
                .group_by(InventoryItem.product_id)
                .subquery()
            )
            q = q.outerjoin(qty_subq, qty_subq.c.product_id == Product.id)
            q = q.filter(func.coalesce(qty_subq.c.total_qty, 0) <= Product.reorder_level)

        return q

    def search(
        self,
        query: Optional[str] = None,
        category_id: Optional[int] = None,
        low_stock_only: bool = False,
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 25,
    ) -> List[Product]:
        q = self._search_query(query, category_id, low_stock_only, is_active)
        return q.order_by(Product.name).offset(skip).limit(limit).all()

    def count_search(
        self,
        query: Optional[str] = None,
        category_id: Optional[int] = None,
        low_stock_only: bool = False,
        is_active: Optional[bool] = True,
    ) -> int:
        """Total matching rows, ignoring pagination — used to render 'Showing X of Y' and page controls."""
        q = self._search_query(query, category_id, low_stock_only, is_active)
        return q.order_by(None).count()

    def get_all_with_relations(self) -> List[Product]:
        return (
            self.db.query(Product)
            .options(joinedload(Product.category), joinedload(Product.inventory_items))
            .order_by(Product.name)
            .all()
        )


class CategoryRepository(BaseRepository[Category]):
    def __init__(self, db: Session):
        super().__init__(Category, db)

    def get_by_name(self, name: str) -> Optional[Category]:
        return self.db.query(Category).filter(Category.name == name).first()

    def list_all(self) -> List[Category]:
        return self.db.query(Category).order_by(Category.name).all()


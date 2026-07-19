from typing import Optional, List

from sqlalchemy.orm import Session, joinedload

from app.models.inventory import InventoryItem
from app.models.transaction import Transaction
from app.repositories.base import BaseRepository


class InventoryRepository(BaseRepository[InventoryItem]):
    def __init__(self, db: Session):
        super().__init__(InventoryItem, db)

    def get_by_product_and_location(
        self, product_id: int, location_id: int
    ) -> Optional[InventoryItem]:
        return (
            self.db.query(InventoryItem)
            .filter(
                InventoryItem.product_id == product_id,
                InventoryItem.location_id == location_id,
            )
            .first()
        )

    def list_by_product(self, product_id: int) -> List[InventoryItem]:
        return (
            self.db.query(InventoryItem)
            .options(joinedload(InventoryItem.location))
            .filter(InventoryItem.product_id == product_id)
            .all()
        )


class TransactionRepository(BaseRepository[Transaction]):
    def __init__(self, db: Session):
        super().__init__(Transaction, db)

    def list_recent(self, limit: int = 20) -> List[Transaction]:
        return (
            self.db.query(Transaction)
            .options(joinedload(Transaction.product), joinedload(Transaction.location))
            .order_by(Transaction.created_at.desc())
            .limit(limit)
            .all()
        )

    def list_all_filtered(
        self,
        product_id: Optional[int] = None,
        transaction_type: Optional[str] = None,
        performed_by: Optional[int] = None,
        skip: int = 0,
        limit: int = 200,
    ) -> List[Transaction]:
        q = self.db.query(Transaction).options(
            joinedload(Transaction.product), joinedload(Transaction.location)
        )
        if product_id:
            q = q.filter(Transaction.product_id == product_id)
        if transaction_type:
            q = q.filter(Transaction.transaction_type == transaction_type)
        if performed_by:
            q = q.filter(Transaction.performed_by == performed_by)
        return q.order_by(Transaction.created_at.desc()).offset(skip).limit(limit).all()

    def count_filtered(
        self,
        product_id: Optional[int] = None,
        transaction_type: Optional[str] = None,
        performed_by: Optional[int] = None,
    ) -> int:
        q = self.db.query(Transaction)
        if product_id:
            q = q.filter(Transaction.product_id == product_id)
        if transaction_type:
            q = q.filter(Transaction.transaction_type == transaction_type)
        if performed_by:
            q = q.filter(Transaction.performed_by == performed_by)
        return q.order_by(None).count()

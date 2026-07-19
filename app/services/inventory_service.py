"""
Core inventory operations: Stock In, Stock Out, and Stock Adjustment.

Every operation:
  1. Loads (or creates) the InventoryItem row for the product/location pair.
  2. Applies the movement as a single ATOMIC SQL statement (see the
     concurrency note below) rather than a Python read-modify-write.
  3. Writes an immutable Transaction ledger entry capturing before/after
     quantities, so the full movement history can always be reconstructed
     and audited.

CONCURRENCY NOTE (read this before touching stock_in/stock_out):
------------------------------------------------------------------
The old implementation did:

    item.quantity -= data.quantity   # read old value in Python
    self.inv_repo.update(item)       # write new value back

This is a classic read-modify-write race. If two requests for the same
product/location both read quantity=5 before either commits, and both
try to take out 5 units, BOTH would pass the "is there enough stock?"
check (5 >= 5), and both would write back quantity=0 — even though
only one of those stock-outs should have succeeded. The second one
oversold, silently.

The fix: push the check-and-update into a single atomic SQL statement,
using the database's own row-level write atomicity instead of
Python-level logic:

    UPDATE inventory_items
    SET quantity = quantity - :qty
    WHERE id = :id AND quantity >= :qty

If two requests race, the database guarantees only one UPDATE can
apply at a time per row. Whichever commits first changes the row;
the second one re-evaluates `quantity >= :qty` against the ALREADY
UPDATED value and its WHERE clause fails to match if there isn't
enough left — so its rowcount is 0, and we correctly reject it with
"insufficient stock" instead of allowing an oversell.

This works today with SQLite (which serializes writes at the database
level) and is also the correct, portable pattern for Postgres/MySQL
under real concurrent load — no code changes needed if the database
is swapped later.
"""
import logging
import uuid
from typing import List, Optional, Tuple

from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory import InventoryItem
from app.models.transaction import Transaction, TransactionType
from app.repositories.inventory_repository import InventoryRepository, TransactionRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.inventory import StockInRequest, StockOutRequest, StockAdjustmentRequest, TransferRequest
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class InventoryServiceError(Exception):
    pass


class InventoryService:
    def __init__(self, db: Session):
        self.db = db
        self.inv_repo = InventoryRepository(db)
        self.txn_repo = TransactionRepository(db)
        self.product_repo = ProductRepository(db)
        self.audit = AuditService(db)

    def _get_or_create_item(self, product_id: int, location_id: int) -> InventoryItem:
        """
        Gets the InventoryItem row, creating it (starting at quantity=0)
        if this is the first time this product has ever been stocked at
        this location. If two requests race to create the same
        product/location row for the first time, the unique constraint
        on (product_id, location_id) means only one INSERT wins — we
        catch that and re-fetch the row the other request just created.
        """
        item = self.inv_repo.get_by_product_and_location(product_id, location_id)
        if item:
            return item
        try:
            item = InventoryItem(product_id=product_id, location_id=location_id, quantity=0)
            return self.inv_repo.create(item)
        except IntegrityError:
            self.db.rollback()
            item = self.inv_repo.get_by_product_and_location(product_id, location_id)
            if not item:
                raise  # something else is wrong; don't swallow it
            return item

    def stock_in(self, data: StockInRequest, user_id: int) -> Transaction:
        product = self.product_repo.get(data.product_id)
        if not product:
            raise InventoryServiceError("Product not found.")

        item = self._get_or_create_item(data.product_id, data.location_id)

        # Atomic increment — see module docstring. Not strictly required
        # for correctness on the "in" side (there's no lower bound to
        # violate), but doing it atomically avoids a lost update if two
        # stock-ins land on the same row at the same time.
        self.db.execute(
            sa_update(InventoryItem)
            .where(InventoryItem.id == item.id)
            .values(quantity=InventoryItem.quantity + data.quantity)
        )
        self.db.commit()
        self.db.refresh(item)

        after = item.quantity
        before = after - data.quantity

        txn = Transaction(
            product_id=data.product_id,
            location_id=data.location_id,
            transaction_type=TransactionType.STOCK_IN,
            quantity=data.quantity,
            quantity_before=before,
            quantity_after=after,
            unit_price_snapshot=product.price,
            reference=data.reference,
            notes=data.notes,
            performed_by=user_id,
        )
        txn = self.txn_repo.create(txn)
        logger.info(
            "STOCK_IN product=%s location=%s qty=%s (%s -> %s)",
            product.product_code, data.location_id, data.quantity, before, after,
        )
        self._check_low_stock(product)
        return txn

    def stock_out(self, data: StockOutRequest, user_id: int) -> Transaction:
        product = self.product_repo.get(data.product_id)
        if not product:
            raise InventoryServiceError("Product not found.")

        item = self.inv_repo.get_by_product_and_location(data.product_id, data.location_id)
        if not item:
            raise InventoryServiceError(
                f"Insufficient stock. Available: 0, requested: {data.quantity}."
            )

        # Atomic conditional decrement — the WHERE clause re-checks
        # quantity >= requested against whatever value is committed at
        # the moment this statement actually runs, not a value we read
        # earlier in Python. If another request already took the stock
        # out from under us, this UPDATE simply matches zero rows.
        result = self.db.execute(
            sa_update(InventoryItem)
            .where(InventoryItem.id == item.id, InventoryItem.quantity >= data.quantity)
            .values(quantity=InventoryItem.quantity - data.quantity)
        )

        if result.rowcount == 0:
            self.db.rollback()
            self.db.refresh(item)
            raise InventoryServiceError(
                f"Insufficient stock. Available: {item.quantity}, requested: {data.quantity}."
            )

        self.db.commit()
        self.db.refresh(item)

        after = item.quantity
        before = after + data.quantity

        txn = Transaction(
            product_id=data.product_id,
            location_id=data.location_id,
            transaction_type=TransactionType.STOCK_OUT,
            quantity=data.quantity,
            quantity_before=before,
            quantity_after=after,
            unit_price_snapshot=product.price,
            reference=data.reference,
            notes=data.notes,
            performed_by=user_id,
        )
        txn = self.txn_repo.create(txn)
        logger.info(
            "STOCK_OUT product=%s location=%s qty=%s (%s -> %s)",
            product.product_code, data.location_id, data.quantity, before, after,
        )
        self._check_low_stock(product)
        return txn

    def adjust_stock(self, data: StockAdjustmentRequest, user_id: int) -> Transaction:
        """
        Sets the quantity to an exact value (e.g. after a physical
        stock count). This is intentionally last-write-wins under
        concurrency: an adjustment represents "the true count is X,"
        not a relative change, so if two adjustments race, the final
        state should be whichever count was submitted last — there's no
        "insufficient stock" concept to protect here the way there is
        for stock_out.
        """
        product = self.product_repo.get(data.product_id)
        if not product:
            raise InventoryServiceError("Product not found.")

        item = self._get_or_create_item(data.product_id, data.location_id)
        before = item.quantity
        delta = data.new_quantity - before
        item.quantity = data.new_quantity
        item = self.inv_repo.update(item)

        txn = Transaction(
            product_id=data.product_id,
            location_id=data.location_id,
            transaction_type=TransactionType.ADJUSTMENT,
            quantity=abs(delta),
            quantity_before=before,
            quantity_after=item.quantity,
            unit_price_snapshot=product.price,
            reference=None,
            notes=data.notes or f"Manual adjustment ({'+' if delta >= 0 else ''}{delta})",
            performed_by=user_id,
        )
        txn = self.txn_repo.create(txn)
        logger.info(
            "ADJUSTMENT product=%s location=%s (%s -> %s)",
            product.product_code, data.location_id, before, item.quantity,
        )
        self._check_low_stock(product)
        return txn

    def transfer_stock(self, data: TransferRequest, user_id: int) -> Tuple[Transaction, Transaction]:
        """
        Moves stock from one location to another for the same product,
        as a single atomic operation recorded as a LINKED PAIR of
        ledger entries (TRANSFER_OUT at the source, TRANSFER_IN at the
        destination), sharing a common `reference` value so the two
        sides of the move can always be traced back to each other in
        the transaction history.

        Unlike stock_in/stock_out (which each commit their own atomic
        statement independently), this method deliberately holds BOTH
        the decrement and the increment in a single uncommitted
        database transaction and only commits once at the end — so a
        transfer can never be observed half-applied (stock vanished
        from the source but never arrived at the destination). If the
        source doesn't have enough stock, we roll back before touching
        the destination at all.

        The destination InventoryItem row is created (if it doesn't
        exist yet) via _get_or_create_item BEFORE the transfer proper
        begins. That's safe to do independently — an empty (quantity=0)
        row grants no stock on its own — so it doesn't need to be part
        of the same atomic block.
        """
        product = self.product_repo.get(data.product_id)
        if not product:
            raise InventoryServiceError("Product not found.")

        from_item = self.inv_repo.get_by_product_and_location(data.product_id, data.from_location_id)
        if not from_item:
            raise InventoryServiceError(
                f"Insufficient stock at the source location. Available: 0, requested: {data.quantity}."
            )

        to_item = self._get_or_create_item(data.product_id, data.to_location_id)
        to_before = to_item.quantity

        # Atomic conditional decrement at the source — same pattern as
        # stock_out. Not committed yet: if this fails, nothing else in
        # this transfer has touched the database's committed state.
        result = self.db.execute(
            sa_update(InventoryItem)
            .where(InventoryItem.id == from_item.id, InventoryItem.quantity >= data.quantity)
            .values(quantity=InventoryItem.quantity - data.quantity)
        )
        if result.rowcount == 0:
            self.db.rollback()
            self.db.refresh(from_item)
            raise InventoryServiceError(
                f"Insufficient stock at the source location. "
                f"Available: {from_item.quantity}, requested: {data.quantity}."
            )

        # Atomic increment at the destination — part of the SAME
        # uncommitted transaction as the decrement above.
        self.db.execute(
            sa_update(InventoryItem)
            .where(InventoryItem.id == to_item.id)
            .values(quantity=InventoryItem.quantity + data.quantity)
        )

        self.db.commit()
        self.db.refresh(from_item)
        self.db.refresh(to_item)

        from_after = from_item.quantity
        from_before = from_after + data.quantity
        to_after = to_item.quantity

        transfer_ref = f"TRANSFER-{uuid.uuid4().hex[:8].upper()}"

        txn_out = Transaction(
            product_id=data.product_id,
            location_id=data.from_location_id,
            transaction_type=TransactionType.TRANSFER_OUT,
            quantity=data.quantity,
            quantity_before=from_before,
            quantity_after=from_after,
            unit_price_snapshot=product.price,
            reference=transfer_ref,
            notes=data.notes,
            performed_by=user_id,
        )
        txn_in = Transaction(
            product_id=data.product_id,
            location_id=data.to_location_id,
            transaction_type=TransactionType.TRANSFER_IN,
            quantity=data.quantity,
            quantity_before=to_before,
            quantity_after=to_after,
            unit_price_snapshot=product.price,
            reference=transfer_ref,
            notes=data.notes,
            performed_by=user_id,
        )
        txn_out = self.txn_repo.create(txn_out)
        txn_in = self.txn_repo.create(txn_in)

        logger.info(
            "TRANSFER product=%s ref=%s from_location=%s(%s->%s) to_location=%s(%s->%s)",
            product.product_code, transfer_ref,
            data.from_location_id, from_before, from_after,
            data.to_location_id, to_before, to_after,
        )
        # Total quantity across all locations is unchanged by a
        # transfer, so this is mostly a no-op — but it's cheap and
        # keeps behavior consistent with the other operations.
        self._check_low_stock(product)
        return txn_out, txn_in

    def _check_low_stock(self, product) -> None:
        # Refresh relationship data before evaluating
        self.db.refresh(product)
        if product.is_low_stock:
            logger.warning(
                "LOW STOCK ALERT: %s (%s) has %s units, reorder level %s",
                product.name, product.product_code, product.total_quantity, product.reorder_level,
            )

    def get_recent_transactions(self, limit: int = 20) -> List[Transaction]:
        return self.txn_repo.list_recent(limit)

    def get_transactions_filtered(
        self, product_id: Optional[int] = None, transaction_type: Optional[str] = None,
        performed_by: Optional[int] = None, skip: int = 0, limit: int = 200,
    ) -> List[Transaction]:
        return self.txn_repo.list_all_filtered(product_id, transaction_type, performed_by, skip, limit)

    def count_transactions_filtered(
        self, product_id: Optional[int] = None, transaction_type: Optional[str] = None,
        performed_by: Optional[int] = None,
    ) -> int:
        return self.txn_repo.count_filtered(product_id, transaction_type, performed_by)

    def get_inventory_for_product(self, product_id: int) -> List[InventoryItem]:
        return self.inv_repo.list_by_product(product_id)

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.transaction import Transaction, TransactionType
from app.repositories.product_repository import ProductRepository
from app.repositories.inventory_repository import TransactionRepository


@dataclass
class DashboardMetrics:
    total_products: int
    total_active_products: int
    total_inventory_value: float
    total_units_in_stock: int
    low_stock_items: List[Product]
    recent_transactions: List[Transaction]


class DashboardService:
    def __init__(self, db: Session):
        self.db = db
        self.product_repo = ProductRepository(db)
        self.txn_repo = TransactionRepository(db)

    def get_metrics(self) -> DashboardMetrics:
        products = self.product_repo.get_all_with_relations()
        active_products = [p for p in products if p.is_active]

        total_value = sum(p.total_value for p in active_products)
        total_units = sum(p.total_quantity for p in active_products)
        low_stock = [p for p in active_products if p.is_low_stock]
        recent_txns = self.txn_repo.list_recent(limit=10)

        return DashboardMetrics(
            total_products=len(products),
            total_active_products=len(active_products),
            total_inventory_value=round(total_value, 2),
            total_units_in_stock=total_units,
            low_stock_items=low_stock,
            recent_transactions=recent_txns,
        )

    def get_stock_movement_trend(self, days: int = 14) -> Dict[str, List]:
        """
        Daily totals of stock-in vs stock-out quantity for the last N
        days, for the dashboard trend chart. Days with zero activity
        are included as 0 (not omitted), so the chart's x-axis is a
        continuous, evenly-spaced timeline rather than skipping gaps.
        """
        start_date = (datetime.utcnow() - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        rows = (
            self.db.query(
                func.date(Transaction.created_at).label("day"),
                Transaction.transaction_type,
                func.sum(Transaction.quantity).label("total_qty"),
            )
            .filter(Transaction.created_at >= start_date)
            .filter(Transaction.transaction_type.in_([TransactionType.STOCK_IN, TransactionType.STOCK_OUT]))
            .group_by(func.date(Transaction.created_at), Transaction.transaction_type)
            .all()
        )

        # Build a lookup: {date_string: {"in": qty, "out": qty}}
        by_day: Dict[str, Dict[str, int]] = {}
        for day, txn_type, total_qty in rows:
            day_str = str(day)
            by_day.setdefault(day_str, {"in": 0, "out": 0})
            if txn_type == TransactionType.STOCK_IN:
                by_day[day_str]["in"] = int(total_qty or 0)
            elif txn_type == TransactionType.STOCK_OUT:
                by_day[day_str]["out"] = int(total_qty or 0)

        labels, stock_in, stock_out = [], [], []
        for i in range(days):
            day = (start_date + timedelta(days=i)).date()
            day_str = str(day)
            labels.append(day.strftime("%b %d"))
            stock_in.append(by_day.get(day_str, {}).get("in", 0))
            stock_out.append(by_day.get(day_str, {}).get("out", 0))

        return {"labels": labels, "stock_in": stock_in, "stock_out": stock_out}

    def get_category_value_distribution(self) -> Dict[str, List]:
        """
        Total inventory value grouped by category, for the dashboard's
        category-breakdown chart. Products with no category are grouped
        under 'Uncategorized'. Computed in Python (not SQL) since
        total_value depends on the total_quantity property, which sums
        across InventoryItem rows — simplest to keep that logic in one
        place rather than duplicating it as a SQL aggregate.
        """
        products = self.product_repo.get_all_with_relations()
        totals: Dict[str, float] = {}
        for p in products:
            if not p.is_active:
                continue
            category_name = p.category.name if p.category else "Uncategorized"
            totals[category_name] = totals.get(category_name, 0.0) + p.total_value

        # Sort descending by value so the largest slice is first/most visible
        sorted_items = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        return {
            "labels": [name for name, _ in sorted_items],
            "values": [round(value, 2) for _, value in sorted_items],
        }

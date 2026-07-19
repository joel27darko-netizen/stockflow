import enum
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text, Float
from sqlalchemy.orm import relationship

from app.database import Base


class TransactionType(str, enum.Enum):
    STOCK_IN = "stock_in"
    STOCK_OUT = "stock_out"
    ADJUSTMENT = "adjustment"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"


class Transaction(Base):
    """
    Immutable ledger entry for every inventory movement. This is the
    backbone of the audit trail and transaction-history reports.
    """

    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    transaction_type = Column(Enum(TransactionType), nullable=False)
    quantity = Column(Integer, nullable=False)  # always positive; sign implied by type
    quantity_before = Column(Integer, nullable=False)
    quantity_after = Column(Integer, nullable=False)
    unit_price_snapshot = Column(Float, nullable=False, default=0.0)
    reference = Column(String(120), nullable=True)  # e.g. supplier invoice / sales order no.
    notes = Column(Text, nullable=True)
    performed_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    product = relationship("Product", back_populates="transactions")
    location = relationship("Location")
    performed_by_user = relationship("User", back_populates="transactions")

    def __repr__(self):
        return f"<Transaction {self.transaction_type} product={self.product_id} qty={self.quantity}>"

from datetime import datetime

from sqlalchemy import Column, Integer, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class InventoryItem(Base):
    """
    Represents the quantity of a specific product held at a specific
    warehouse location. A product can have many InventoryItem rows
    (one per location it is stocked in).
    """

    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("product_id", "location_id", name="uq_product_location"),
    )

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", back_populates="inventory_items")
    location = relationship("Location", back_populates="inventory_items")

    def __repr__(self):
        return f"<InventoryItem product={self.product_id} location={self.location_id} qty={self.quantity}>"

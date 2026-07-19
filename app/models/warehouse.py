from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship

from app.database import Base


class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), unique=True, nullable=False)
    address = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    locations = relationship(
        "Location", back_populates="warehouse", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Warehouse {self.name}>"


class Location(Base):
    """A shelf/zone/bin within a warehouse, e.g. 'A1-Shelf3'."""

    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    zone = Column(String(50), nullable=False)
    shelf = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    warehouse = relationship("Warehouse", back_populates="locations")
    inventory_items = relationship("InventoryItem", back_populates="location")

    @property
    def display_name(self) -> str:
        return f"{self.zone}" + (f" / {self.shelf}" if self.shelf else "")

    def __repr__(self):
        return f"<Location {self.display_name} @ warehouse {self.warehouse_id}>"

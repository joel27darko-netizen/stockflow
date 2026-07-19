from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from app.database import Base


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(255), nullable=True)

    products = relationship("Product", back_populates="category")

    def __repr__(self):
        return f"<Category {self.name}>"


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    product_code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(150), nullable=False, index=True)
    description = Column(Text, nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    price = Column(Float, nullable=False, default=0.0)
    reorder_level = Column(Integer, nullable=False, default=10)
    is_active = Column(Boolean, default=True)

    qr_code_path = Column(String(255), nullable=True)
    barcode_path = Column(String(255), nullable=True)
    barcode_value = Column(String(50), unique=True, nullable=True)
    image_path = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("Category", back_populates="products")
    inventory_items = relationship(
        "InventoryItem", back_populates="product", cascade="all, delete-orphan"
    )
    transactions = relationship("Transaction", back_populates="product")

    @property
    def total_quantity(self) -> int:
        """Sum of quantities across all warehouse locations."""
        return sum(item.quantity for item in self.inventory_items)

    @property
    def total_value(self) -> float:
        return self.total_quantity * self.price

    @property
    def is_low_stock(self) -> bool:
        return self.total_quantity <= self.reorder_level

    def __repr__(self):
        return f"<Product {self.product_code} - {self.name}>"

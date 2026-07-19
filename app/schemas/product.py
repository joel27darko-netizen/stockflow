from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class CategoryBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None


class CategoryCreate(CategoryBase):
    pass


class CategoryOut(CategoryBase):
    id: int

    class Config:
        from_attributes = True


class ProductBase(BaseModel):
    product_code: Optional[str] = Field(
        None, max_length=50,
        description="Leave blank to auto-generate a unique code. If provided, it must be unique.",
    )
    name: str = Field(..., min_length=2, max_length=150)
    description: Optional[str] = None
    category_id: Optional[int] = None
    price: float = Field(..., ge=0)
    reorder_level: int = Field(default=10, ge=0)

    @field_validator("product_code")
    @classmethod
    def normalize_code(cls, v: Optional[str]) -> Optional[str]:
        """
        Treats a blank/whitespace-only code the same as "not provided" —
        this is what tells the service layer to auto-generate one — and
        otherwise normalizes a manually-entered code to uppercase, matching
        how codes are stored and looked up everywhere else in the app.
        """
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned.upper() if cleaned else None


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    description: Optional[str] = None
    category_id: Optional[int] = None
    price: Optional[float] = Field(None, ge=0)
    reorder_level: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class ProductOut(ProductBase):
    id: int
    product_code: str  # always populated once persisted — never None on output
    is_active: bool
    qr_code_path: Optional[str] = None
    barcode_path: Optional[str] = None
    barcode_value: Optional[str] = None
    image_path: Optional[str] = None
    created_at: datetime
    total_quantity: int = 0
    total_value: float = 0.0
    is_low_stock: bool = False

    class Config:
        from_attributes = True

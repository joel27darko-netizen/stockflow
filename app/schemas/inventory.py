from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.models.transaction import TransactionType


class StockInRequest(BaseModel):
    product_id: int
    location_id: int
    quantity: int = Field(..., gt=0)
    reference: Optional[str] = None
    notes: Optional[str] = None


class StockOutRequest(BaseModel):
    product_id: int
    location_id: int
    quantity: int = Field(..., gt=0)
    reference: Optional[str] = None
    notes: Optional[str] = None


class StockAdjustmentRequest(BaseModel):
    product_id: int
    location_id: int
    new_quantity: int = Field(..., ge=0)
    notes: Optional[str] = None


class TransferRequest(BaseModel):
    product_id: int
    from_location_id: int
    to_location_id: int
    quantity: int = Field(..., gt=0)
    notes: Optional[str] = None

    @model_validator(mode="after")
    def locations_must_differ(self) -> "TransferRequest":
        if self.from_location_id == self.to_location_id:
            raise ValueError("Source and destination locations must be different.")
        return self


class InventoryItemOut(BaseModel):
    id: int
    product_id: int
    location_id: int
    quantity: int
    updated_at: datetime

    class Config:
        from_attributes = True


class TransactionOut(BaseModel):
    id: int
    product_id: int
    location_id: int
    transaction_type: TransactionType
    quantity: int
    quantity_before: int
    quantity_after: int
    unit_price_snapshot: float
    reference: Optional[str]
    notes: Optional[str]
    performed_by: int
    created_at: datetime

    class Config:
        from_attributes = True

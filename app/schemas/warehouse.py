from typing import Optional

from pydantic import BaseModel, Field


class WarehouseBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    address: Optional[str] = None


class WarehouseCreate(WarehouseBase):
    pass


class WarehouseOut(WarehouseBase):
    id: int

    class Config:
        from_attributes = True


class LocationBase(BaseModel):
    warehouse_id: int
    zone: str = Field(..., min_length=1, max_length=50)
    shelf: Optional[str] = None
    notes: Optional[str] = None


class LocationCreate(LocationBase):
    pass


class LocationOut(LocationBase):
    id: int

    class Config:
        from_attributes = True

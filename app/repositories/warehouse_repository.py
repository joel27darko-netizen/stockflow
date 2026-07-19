from typing import List

from sqlalchemy.orm import Session

from app.models.warehouse import Warehouse, Location
from app.repositories.base import BaseRepository


class WarehouseRepository(BaseRepository[Warehouse]):
    def __init__(self, db: Session):
        super().__init__(Warehouse, db)

    def list_all(self, include_inactive: bool = False) -> List[Warehouse]:
        q = self.db.query(Warehouse)
        if not include_inactive:
            q = q.filter(Warehouse.is_active.is_(True))
        return q.order_by(Warehouse.name).all()


class LocationRepository(BaseRepository[Location]):
    def __init__(self, db: Session):
        super().__init__(Location, db)

    def list_by_warehouse(self, warehouse_id: int, include_inactive: bool = False) -> List[Location]:
        q = self.db.query(Location).filter(Location.warehouse_id == warehouse_id)
        if not include_inactive:
            q = q.filter(Location.is_active.is_(True))
        return q.order_by(Location.zone).all()

    def list_all(self, include_inactive: bool = False) -> List[Location]:
        q = self.db.query(Location)
        if not include_inactive:
            q = q.filter(Location.is_active.is_(True))
        return q.order_by(Location.warehouse_id, Location.zone).all()

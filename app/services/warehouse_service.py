import logging
from typing import List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.warehouse import Warehouse, Location
from app.repositories.warehouse_repository import WarehouseRepository, LocationRepository
from app.schemas.warehouse import WarehouseCreate, LocationCreate
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class WarehouseServiceError(Exception):
    pass


class WarehouseService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = WarehouseRepository(db)
        self.location_repo = LocationRepository(db)
        self.audit = AuditService(db)

    # ---------- Warehouses ----------
    def create_warehouse(self, data: WarehouseCreate, user_id: int) -> Warehouse:
        # Check against ALL warehouses (including inactive/soft-deleted
        # ones) since `name` has a DB-level unique constraint — creating
        # a duplicate of a deactivated warehouse's name would otherwise
        # fail with a raw IntegrityError instead of a friendly message.
        existing = [w for w in self.repo.list_all(include_inactive=True) if w.name.lower() == data.name.lower()]
        if existing:
            raise WarehouseServiceError(
                f"A warehouse named '{data.name}' already exists"
                + (" (currently inactive)." if not existing[0].is_active else ".")
            )
        warehouse = Warehouse(name=data.name, address=data.address)
        warehouse = self.repo.create(warehouse)
        self.audit.log(user_id, "CREATE_WAREHOUSE", "Warehouse", warehouse.id, data.name)
        logger.info("Warehouse created: %s", warehouse.name)
        return warehouse

    def list_warehouses(self, include_inactive: bool = False) -> List[Warehouse]:
        return self.repo.list_all(include_inactive=include_inactive)

    def deactivate_warehouse(self, warehouse_id: int, user_id: int) -> Warehouse:
        warehouse = self.repo.get(warehouse_id)
        if not warehouse:
            raise WarehouseServiceError("Warehouse not found.")
        warehouse.is_active = False
        warehouse = self.repo.update(warehouse)
        self.audit.log(user_id, "DEACTIVATE_WAREHOUSE", "Warehouse", warehouse.id, warehouse.name)
        logger.info("Warehouse deactivated: %s", warehouse.name)
        return warehouse

    def reactivate_warehouse(self, warehouse_id: int, user_id: int) -> Warehouse:
        warehouse = self.repo.get(warehouse_id)
        if not warehouse:
            raise WarehouseServiceError("Warehouse not found.")
        warehouse.is_active = True
        warehouse = self.repo.update(warehouse)
        self.audit.log(user_id, "REACTIVATE_WAREHOUSE", "Warehouse", warehouse.id, warehouse.name)
        logger.info("Warehouse reactivated: %s", warehouse.name)
        return warehouse

    def delete_warehouse(self, warehouse_id: int, user_id: int) -> None:
        """
        Permanently deletes a warehouse (and, via cascade, its
        locations). Only allowed if none of its locations have any
        stock transaction history — otherwise this would violate the
        Transaction table's foreign key and should be deactivated
        instead to preserve the audit trail.
        """
        warehouse = self.repo.get(warehouse_id)
        if not warehouse:
            raise WarehouseServiceError("Warehouse not found.")
        name = warehouse.name
        try:
            self.repo.delete(warehouse)
        except IntegrityError:
            self.db.rollback()
            raise WarehouseServiceError(
                f"'{name}' cannot be deleted because one or more of its locations has transaction history. "
                "Deactivate it instead to preserve the audit trail."
            )
        self.audit.log(user_id, "DELETE_WAREHOUSE", "Warehouse", warehouse_id, name)
        logger.info("Warehouse deleted: %s", name)

    # ---------- Locations ----------
    def create_location(self, data: LocationCreate, user_id: int) -> Location:
        if not self.repo.get(data.warehouse_id):
            raise WarehouseServiceError("Parent warehouse does not exist.")
        location = Location(
            warehouse_id=data.warehouse_id,
            zone=data.zone,
            shelf=data.shelf,
            notes=data.notes,
        )
        location = self.location_repo.create(location)
        self.audit.log(user_id, "CREATE_LOCATION", "Location", location.id, data.zone)
        logger.info("Location created: %s in warehouse %s", location.zone, data.warehouse_id)
        return location

    def list_locations(self, include_inactive: bool = False) -> List[Location]:
        return self.location_repo.list_all(include_inactive=include_inactive)

    def list_locations_for_warehouse(self, warehouse_id: int, include_inactive: bool = False) -> List[Location]:
        return self.location_repo.list_by_warehouse(warehouse_id, include_inactive=include_inactive)

    def deactivate_location(self, location_id: int, user_id: int) -> Location:
        location = self.location_repo.get(location_id)
        if not location:
            raise WarehouseServiceError("Location not found.")
        location.is_active = False
        location = self.location_repo.update(location)
        self.audit.log(user_id, "DEACTIVATE_LOCATION", "Location", location.id, location.display_name)
        logger.info("Location deactivated: %s", location.display_name)
        return location

    def reactivate_location(self, location_id: int, user_id: int) -> Location:
        location = self.location_repo.get(location_id)
        if not location:
            raise WarehouseServiceError("Location not found.")
        location.is_active = True
        location = self.location_repo.update(location)
        self.audit.log(user_id, "REACTIVATE_LOCATION", "Location", location.id, location.display_name)
        logger.info("Location reactivated: %s", location.display_name)
        return location

    def delete_location(self, location_id: int, user_id: int) -> None:
        """Permanently deletes a location; blocked if it has transaction history (deactivate instead)."""
        location = self.location_repo.get(location_id)
        if not location:
            raise WarehouseServiceError("Location not found.")
        name = location.display_name
        try:
            self.location_repo.delete(location)
        except IntegrityError:
            self.db.rollback()
            raise WarehouseServiceError(
                f"'{name}' cannot be deleted because it has transaction history. "
                "Deactivate it instead to preserve the audit trail."
            )
        self.audit.log(user_id, "DELETE_LOCATION", "Location", location_id, name)
        logger.info("Location deleted: %s", name)

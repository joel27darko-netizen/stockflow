from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.flash import redirect_with_flash
from app.database import get_db
from app.dependencies import require_any_role, require_manager_or_admin
from app.schemas.warehouse import WarehouseCreate, LocationCreate
from app.services.warehouse_service import WarehouseService, WarehouseServiceError

router = APIRouter(prefix="/warehouses", tags=["warehouses"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def list_warehouses(
    request: Request, show_inactive: bool = False,
    db: Session = Depends(get_db), current=Depends(require_any_role),
):
    service = WarehouseService(db)
    warehouses = service.list_warehouses(include_inactive=show_inactive)
    locations = service.list_locations(include_inactive=show_inactive)
    return templates.TemplateResponse(request, "warehouses/list.html",
        {
            "request": request, "warehouses": warehouses, "locations": locations,
            "current_user": current, "error": None, "show_inactive": show_inactive,
        },
    )


@router.post("/new", response_class=HTMLResponse)
def create_warehouse(
    request: Request, name: str = Form(...), address: str = Form(""),
    db: Session = Depends(get_db), current=Depends(require_manager_or_admin),
):
    service = WarehouseService(db)
    try:
        warehouse = service.create_warehouse(WarehouseCreate(name=name, address=address), current.id)
    except WarehouseServiceError as e:
        warehouses = service.list_warehouses()
        locations = service.list_locations()
        return templates.TemplateResponse(request, "warehouses/list.html",
            {"request": request, "warehouses": warehouses, "locations": locations, "current_user": current,
             "error": str(e), "show_inactive": False},
            status_code=400,
        )
    return redirect_with_flash("/warehouses", f"Warehouse '{warehouse.name}' created successfully.")


@router.post("/{warehouse_id}/deactivate")
def deactivate_warehouse(warehouse_id: int, db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    service = WarehouseService(db)
    try:
        warehouse = service.deactivate_warehouse(warehouse_id, current.id)
        return redirect_with_flash(
            "/warehouses",
            f"'{warehouse.name}' has been deactivated. Its locations are hidden from new stock operations "
            "but existing history is preserved.",
        )
    except WarehouseServiceError as e:
        return redirect_with_flash("/warehouses", str(e), "danger")


@router.post("/{warehouse_id}/reactivate")
def reactivate_warehouse(warehouse_id: int, db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    service = WarehouseService(db)
    try:
        warehouse = service.reactivate_warehouse(warehouse_id, current.id)
        return redirect_with_flash("/warehouses", f"'{warehouse.name}' has been reactivated.")
    except WarehouseServiceError as e:
        return redirect_with_flash("/warehouses", str(e), "danger")


@router.post("/{warehouse_id}/delete")
def delete_warehouse(warehouse_id: int, db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    service = WarehouseService(db)
    try:
        warehouse = service.repo.get(warehouse_id)
        name = warehouse.name if warehouse else "Warehouse"
        service.delete_warehouse(warehouse_id, current.id)
        return redirect_with_flash("/warehouses", f"'{name}' was permanently deleted.")
    except WarehouseServiceError as e:
        return redirect_with_flash("/warehouses", str(e), "danger")


@router.post("/locations/new", response_class=HTMLResponse)
def create_location(
    request: Request, warehouse_id: int = Form(...), zone: str = Form(...),
    shelf: str = Form(""), notes: str = Form(""),
    db: Session = Depends(get_db), current=Depends(require_manager_or_admin),
):
    service = WarehouseService(db)
    try:
        location = service.create_location(
            LocationCreate(warehouse_id=warehouse_id, zone=zone, shelf=shelf, notes=notes), current.id
        )
    except WarehouseServiceError as e:
        warehouses = service.list_warehouses()
        locations = service.list_locations()
        return templates.TemplateResponse(request, "warehouses/list.html",
            {"request": request, "warehouses": warehouses, "locations": locations, "current_user": current,
             "error": str(e), "show_inactive": False},
            status_code=400,
        )
    return redirect_with_flash("/warehouses", f"Location '{location.display_name}' added successfully.")


@router.post("/locations/{location_id}/deactivate")
def deactivate_location(location_id: int, db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    service = WarehouseService(db)
    try:
        location = service.deactivate_location(location_id, current.id)
        return redirect_with_flash("/warehouses", f"Location '{location.display_name}' has been deactivated.")
    except WarehouseServiceError as e:
        return redirect_with_flash("/warehouses", str(e), "danger")


@router.post("/locations/{location_id}/reactivate")
def reactivate_location(location_id: int, db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    service = WarehouseService(db)
    try:
        location = service.reactivate_location(location_id, current.id)
        return redirect_with_flash("/warehouses", f"Location '{location.display_name}' has been reactivated.")
    except WarehouseServiceError as e:
        return redirect_with_flash("/warehouses", str(e), "danger")


@router.post("/locations/{location_id}/delete")
def delete_location(location_id: int, db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    service = WarehouseService(db)
    try:
        location = service.location_repo.get(location_id)
        name = location.display_name if location else "Location"
        service.delete_location(location_id, current.id)
        return redirect_with_flash("/warehouses", f"Location '{name}' was permanently deleted.")
    except WarehouseServiceError as e:
        return redirect_with_flash("/warehouses", str(e), "danger")

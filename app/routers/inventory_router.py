from typing import Optional

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.flash import redirect_with_flash
from app.database import get_db
from app.dependencies import require_any_role
from app.schemas.inventory import StockInRequest, StockOutRequest, StockAdjustmentRequest
from app.services.inventory_service import InventoryService, InventoryServiceError
from app.services.product_service import ProductService
from app.services.warehouse_service import WarehouseService

router = APIRouter(prefix="/inventory", tags=["inventory"])
templates = Jinja2Templates(directory="app/templates")


def _parse_optional_int(raw: Optional[str]) -> Optional[int]:
    """
    Turns a raw query-string value into Optional[int], treating an
    empty string the same as "not provided". This matters because an
    HTML <select> with <option value=""> (e.g. "All Products") submits
    an EMPTY STRING, not an absent parameter — typing the FastAPI route
    parameter directly as Optional[int] makes FastAPI reject "" with a
    422 before the handler ever runs, which silently breaks the "show
    all" option in any filter dropdown.
    """
    if raw and raw.strip().isdigit():
        return int(raw)
    return None


def _context(db, current, error=None, scanned_product=None):
    return {
        "products": ProductService(db).get_all_products(),
        "locations": WarehouseService(db).list_locations(),
        "current_user": current,
        "error": error,
        "scanned_product": scanned_product,
    }


@router.get("/operations", response_class=HTMLResponse)
def operations_page(request: Request, db: Session = Depends(get_db), current=Depends(require_any_role)):
    ctx = _context(db, current)
    ctx["request"] = request
    return templates.TemplateResponse(request, "inventory/operations.html", ctx)


@router.post("/stock-in", response_class=HTMLResponse)
def stock_in(
    request: Request, product_id: int = Form(...), location_id: int = Form(...),
    quantity: int = Form(...), reference: str = Form(""), notes: str = Form(""),
    db: Session = Depends(get_db), current=Depends(require_any_role),
):
    service = InventoryService(db)
    try:
        txn = service.stock_in(
            StockInRequest(product_id=product_id, location_id=location_id, quantity=quantity, reference=reference, notes=notes),
            current.id,
        )
    except InventoryServiceError as e:
        ctx = _context(db, current, error=str(e))
        ctx["request"] = request
        return templates.TemplateResponse(request, "inventory/operations.html", ctx, status_code=400)
    return redirect_with_flash(
        "/inventory/operations",
        f"Stocked in {quantity} unit(s). New quantity at this location: {txn.quantity_after}.",
    )


@router.post("/stock-out", response_class=HTMLResponse)
def stock_out(
    request: Request, product_id: int = Form(...), location_id: int = Form(...),
    quantity: int = Form(...), reference: str = Form(""), notes: str = Form(""),
    db: Session = Depends(get_db), current=Depends(require_any_role),
):
    service = InventoryService(db)
    try:
        txn = service.stock_out(
            StockOutRequest(product_id=product_id, location_id=location_id, quantity=quantity, reference=reference, notes=notes),
            current.id,
        )
    except InventoryServiceError as e:
        ctx = _context(db, current, error=str(e))
        ctx["request"] = request
        return templates.TemplateResponse(request, "inventory/operations.html", ctx, status_code=400)
    return redirect_with_flash(
        "/inventory/operations",
        f"Stocked out {quantity} unit(s). Remaining quantity at this location: {txn.quantity_after}.",
    )


@router.post("/adjust", response_class=HTMLResponse)
def adjust_stock(
    request: Request, product_id: int = Form(...), location_id: int = Form(...),
    new_quantity: int = Form(...), notes: str = Form(""),
    db: Session = Depends(get_db), current=Depends(require_any_role),
):
    service = InventoryService(db)
    try:
        txn = service.adjust_stock(
            StockAdjustmentRequest(product_id=product_id, location_id=location_id, new_quantity=new_quantity, notes=notes),
            current.id,
        )
    except InventoryServiceError as e:
        ctx = _context(db, current, error=str(e))
        ctx["request"] = request
        return templates.TemplateResponse(request, "inventory/operations.html", ctx, status_code=400)
    return redirect_with_flash(
        "/inventory/operations",
        f"Adjustment applied. Quantity changed from {txn.quantity_before} to {txn.quantity_after}.",
    )


@router.post("/transfer", response_class=HTMLResponse)
def transfer_stock(
    request: Request, product_id: int = Form(...), from_location_id: int = Form(...),
    to_location_id: int = Form(...), quantity: int = Form(...), notes: str = Form(""),
    db: Session = Depends(get_db), current=Depends(require_any_role),
):
    from pydantic import ValidationError
    from app.schemas.inventory import TransferRequest

    service = InventoryService(db)
    try:
        txn_out, txn_in = service.transfer_stock(
            TransferRequest(
                product_id=product_id, from_location_id=from_location_id,
                to_location_id=to_location_id, quantity=quantity, notes=notes,
            ),
            current.id,
        )
    except ValidationError:
        ctx = _context(db, current, error="Source and destination locations must be different.")
        ctx["request"] = request
        return templates.TemplateResponse(request, "inventory/operations.html", ctx, status_code=400)
    except InventoryServiceError as e:
        ctx = _context(db, current, error=str(e))
        ctx["request"] = request
        return templates.TemplateResponse(request, "inventory/operations.html", ctx, status_code=400)
    return redirect_with_flash(
        "/inventory/operations",
        f"Transferred {quantity} unit(s). Source location now has {txn_out.quantity_after}, "
        f"destination now has {txn_in.quantity_after}.",
    )


@router.get("/scanner", response_class=HTMLResponse)
def scanner_page(request: Request, db: Session = Depends(get_db), current=Depends(require_any_role)):
    return templates.TemplateResponse(request, "inventory/scanner.html", {"request": request, "current_user": current, "scanned_product": None, "error": None}
    )


@router.post("/scanner", response_class=HTMLResponse)
def scanner_lookup(
    request: Request, code: str = Form(...),
    db: Session = Depends(get_db), current=Depends(require_any_role),
):
    cleaned_code = code.strip()
    if not cleaned_code:
        return templates.TemplateResponse(request, "inventory/scanner.html",
            {"request": request, "current_user": current, "scanned_product": None,
             "error": "Please enter or scan a product code before looking it up."},
            status_code=400,
        )
    product = ProductService(db).get_by_code_or_barcode(cleaned_code)
    error = None if product else f"No product found for code '{cleaned_code}'. Check the code and try again."
    return templates.TemplateResponse(request, "inventory/scanner.html",
        {"request": request, "current_user": current, "scanned_product": product, "error": error},
    )


@router.get("/transactions", response_class=HTMLResponse)
def transaction_history(
    request: Request,
    product_id: Optional[str] = None,
    transaction_type: Optional[str] = None,
    db: Session = Depends(get_db), current=Depends(require_any_role),
):
    product_id_int = _parse_optional_int(product_id)
    clean_type = transaction_type if transaction_type in ("stock_in", "stock_out", "adjustment") else None

    service = InventoryService(db)
    transactions = service.get_transactions_filtered(product_id=product_id_int, transaction_type=clean_type)
    products = ProductService(db).get_all_products()
    return templates.TemplateResponse(request, "inventory/transactions.html",
        {
            "request": request, "transactions": transactions, "products": products,
            "current_user": current, "product_id": product_id_int, "transaction_type": clean_type or "",
        },
    )


@router.get("/my-activity", response_class=HTMLResponse)
def my_activity(
    request: Request,
    transaction_type: Optional[str] = None,
    page: int = 1,
    db: Session = Depends(get_db), current=Depends(require_any_role),
):
    """
    A personal view of stock movements the current user performed
    themselves — available to every role, not just admins. The full
    /inventory/transactions and /audit-log views (which show everyone's
    activity) stay role-gated as before; this is scoped server-side to
    `performed_by == current.id` so a Staff user can only ever see their
    own history here, regardless of what's passed in the query string.
    """
    clean_type = transaction_type if transaction_type in ("stock_in", "stock_out", "adjustment") else None
    page = max(1, page)
    page_size = 25

    service = InventoryService(db)
    total = service.count_transactions_filtered(transaction_type=clean_type, performed_by=current.id)
    transactions = service.get_transactions_filtered(
        transaction_type=clean_type, performed_by=current.id,
        skip=(page - 1) * page_size, limit=page_size,
    )
    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(request, "inventory/my_activity.html",
        {
            "request": request, "transactions": transactions, "current_user": current,
            "transaction_type": clean_type or "", "total": total, "page": page,
            "total_pages": total_pages, "has_previous": page > 1, "has_next": page < total_pages,
        },
    )

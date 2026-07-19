from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_manager_or_admin
from app.services.inventory_service import InventoryService
from app.services.product_service import ProductService
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["reports"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def reports_page(request: Request, current=Depends(require_manager_or_admin)):
    return templates.TemplateResponse(request, "reports/index.html", {"request": request, "current_user": current})


@router.get("/products/csv")
def export_products_csv(db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    products = ProductService(db).get_all_products()
    buffer = ReportService.products_to_csv(products)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=stockflow_products.csv"},
    )


@router.get("/transactions/csv")
def export_transactions_csv(db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    transactions = InventoryService(db).get_transactions_filtered(limit=5000)
    buffer = ReportService.transactions_to_csv(transactions)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=stockflow_transactions.csv"},
    )


_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/products/xlsx")
def export_products_xlsx(db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    products = ProductService(db).get_all_products()
    buffer = ReportService.products_to_excel(products)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename=stockflow_products.xlsx"},
    )


@router.get("/transactions/xlsx")
def export_transactions_xlsx(db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    transactions = InventoryService(db).get_transactions_filtered(limit=5000)
    buffer = ReportService.transactions_to_excel(transactions)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename=stockflow_transactions.xlsx"},
    )


@router.get("/inventory/pdf")
def export_inventory_pdf(db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    products = ProductService(db).get_all_products()
    total_value = sum(p.total_value for p in products if p.is_active)
    low_stock_count = len([p for p in products if p.is_low_stock and p.is_active])
    buffer = ReportService.build_inventory_summary_pdf(products, total_value, low_stock_count)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=stockflow_inventory_summary.pdf"},
    )

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_any_role
from app.services.dashboard_service import DashboardService

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def root(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/api/notifications/summary")
def notifications_summary(db: Session = Depends(get_db), current=Depends(require_any_role)):
    """
    Small JSON endpoint powering the topbar notification bell. Kept
    separate from the main dashboard route (rather than threading a
    'low_stock_count' variable through every single page's context)
    so the bell can be fetched client-side once, from any page, without
    every router needing to know about it.
    """
    service = DashboardService(db)
    low_stock_items = service.get_metrics().low_stock_items
    return {
        "low_stock_count": len(low_stock_items),
        "items": [
            {"product_code": p.product_code, "name": p.name, "quantity": p.total_quantity}
            for p in low_stock_items[:5]
        ],
    }


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), current=Depends(require_any_role)):
    service = DashboardService(db)
    metrics = service.get_metrics()
    movement_trend = service.get_stock_movement_trend(days=14)
    category_distribution = service.get_category_value_distribution()

    def _safe_json(data) -> str:
        # Standard mitigation for embedding JSON inside a <script> tag:
        # a category/product name containing a literal "</script>" could
        # otherwise break out of the script block. Escaping the forward
        # slash in "</" neutralizes that without affecting valid JSON.
        return json.dumps(data).replace("</", "<\\/")

    return templates.TemplateResponse(request, "dashboard.html",
        {
            "request": request, "metrics": metrics, "current_user": current,
            "movement_trend_json": _safe_json(movement_trend),
            "category_distribution_json": _safe_json(category_distribution),
        },
    )

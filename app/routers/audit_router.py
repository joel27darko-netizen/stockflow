from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit-log", tags=["audit"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def audit_log_page(
    request: Request,
    action: Optional[str] = None,
    page: int = 1,
    db: Session = Depends(get_db),
    current=Depends(require_admin),
):
    service = AuditService(db)
    result = service.search(action=action, page=page)
    actions = service.list_distinct_actions()
    return templates.TemplateResponse(request, "audit/log.html",
        {
            "request": request, "result": result, "actions": actions,
            "current_user": current, "selected_action": action or "",
        },
    )

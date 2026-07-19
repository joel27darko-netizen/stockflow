import logging
from dataclasses import dataclass
from typing import Optional, List

from sqlalchemy.orm import Session, joinedload

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


@dataclass
class AuditLogSearchResult:
    entries: List[AuditLog]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


class AuditService:
    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        user_id: Optional[int],
        action: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        details: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> AuditLog:
        entry = AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=ip_address,
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        logger.info("AUDIT | user=%s action=%s entity=%s:%s", user_id, action, entity_type, entity_id)
        return entry

    def search(
        self,
        action: Optional[str] = None,
        entity_type: Optional[str] = None,
        user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 25,
    ) -> AuditLogSearchResult:
        """Paginated, filterable view of the audit trail for the admin viewer page."""
        page = max(1, page)
        page_size = max(1, min(page_size, 100))

        q = self.db.query(AuditLog).options(joinedload(AuditLog.user))
        if action:
            q = q.filter(AuditLog.action == action)
        if entity_type:
            q = q.filter(AuditLog.entity_type == entity_type)
        if user_id:
            q = q.filter(AuditLog.user_id == user_id)

        total = q.order_by(None).count()
        entries = (
            q.order_by(AuditLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return AuditLogSearchResult(entries=entries, total=total, page=page, page_size=page_size)

    def list_distinct_actions(self) -> List[str]:
        rows = self.db.query(AuditLog.action).distinct().order_by(AuditLog.action).all()
        return [r[0] for r in rows]

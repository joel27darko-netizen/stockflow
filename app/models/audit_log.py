from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.database import Base


class AuditLog(Base):
    """
    Generic audit trail for administrative and CRUD actions (user
    management, product create/update/delete, warehouse changes, login
    events, etc.) — separate from the inventory Transaction ledger.
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)  # e.g. "CREATE_PRODUCT", "LOGIN"
    entity_type = Column(String(50), nullable=True)  # e.g. "Product", "User"
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="audit_logs")

    def __repr__(self):
        return f"<AuditLog {self.action} by user={self.user_id}>"

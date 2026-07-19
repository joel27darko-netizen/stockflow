"""
Shared FastAPI dependencies: current-user resolution from the session
cookie, and role-based access guards.

Since this app serves server-rendered Jinja2 pages (not a pure JSON
API), authentication failures redirect to /login rather than raising a
raw 401, giving a normal browser experience.
"""
from typing import Optional

from fastapi import Depends, Request, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database import get_db
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository

COOKIE_NAME = "stockflow_session"


class RedirectToLogin(Exception):
    """Raised internally then translated to a redirect by middleware/handlers."""


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    user_repo = UserRepository(db)
    user = user_repo.get(payload.get("uid"))
    if not user or not user.is_active:
        return None
    return user


# Paths a user with must_change_password=True is still allowed to hit,
# so we don't create a redirect loop (they need to reach the change
# password page, and always need a way to log out).
_PASSWORD_CHANGE_EXEMPT_PATHS = {"/change-password", "/logout"}


def require_login(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})

    if user.must_change_password and request.url.path not in _PASSWORD_CHANGE_EXEMPT_PATHS:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/change-password"}
        )
    return user


def require_roles(*roles: UserRole):
    def dependency(user: User = Depends(require_login)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return user
    return dependency


require_admin = require_roles(UserRole.ADMIN)
require_manager_or_admin = require_roles(UserRole.ADMIN, UserRole.WAREHOUSE_MANAGER)
require_any_role = require_roles(UserRole.ADMIN, UserRole.WAREHOUSE_MANAGER, UserRole.STAFF)

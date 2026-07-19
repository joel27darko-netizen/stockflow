import logging

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.flash import redirect_with_flash
from app.core.rate_limiter import login_rate_limiter
from app.database import get_db
from app.dependencies import get_current_user, require_login, require_admin, COOKIE_NAME
from app.models.user import User, UserRole
from app.schemas.user import UserCreate
from app.services.auth_service import AuthService, AuthError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "auth/login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    remember_me: bool = Form(False),
    db: Session = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    rate_limit_key = f"{username.strip().lower()}:{client_ip}"

    locked_out, seconds_remaining = login_rate_limiter.check(rate_limit_key)
    if locked_out:
        minutes = max(1, seconds_remaining // 60)
        logger.warning("Login blocked by rate limiter for key=%s (%ss remaining)", rate_limit_key, seconds_remaining)
        return templates.TemplateResponse(request, "auth/login.html",
            {
                "request": request,
                "error": f"Too many failed login attempts. Please try again in about {minutes} minute(s).",
            },
            status_code=429,
        )

    service = AuthService(db)
    try:
        token = service.login(username, password, remember_me=remember_me)
    except AuthError as e:
        login_rate_limiter.record_failure(rate_limit_key)
        return templates.TemplateResponse(request, "auth/login.html", {"request": request, "error": str(e)}, status_code=400
        )

    login_rate_limiter.record_success(rate_limit_key)
    response = RedirectResponse("/dashboard", status_code=303)
    cookie_max_age = 60 * 60 * 24 * 30 if remember_me else 60 * 60 * 8  # 30 days vs 8 hours
    response.set_cookie(COOKIE_NAME, token, httponly=True, max_age=cookie_max_age, samesite="lax")
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/change-password", response_class=HTMLResponse)
def change_password_page(request: Request, current=Depends(require_login)):
    return templates.TemplateResponse(request, "auth/change_password.html",
        {"request": request, "current_user": current, "error": None, "forced": current.must_change_password},
    )


@router.post("/change-password", response_class=HTMLResponse)
def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
    current=Depends(require_login),
):
    if new_password != confirm_password:
        return templates.TemplateResponse(request, "auth/change_password.html",
            {"request": request, "current_user": current, "error": "New password and confirmation do not match.",
             "forced": current.must_change_password},
            status_code=400,
        )

    service = AuthService(db)
    try:
        service.change_password(current.id, current_password, new_password)
    except AuthError as e:
        return templates.TemplateResponse(request, "auth/change_password.html",
            {"request": request, "current_user": current, "error": str(e), "forced": current.must_change_password},
            status_code=400,
        )
    return redirect_with_flash("/dashboard", "Your password has been changed successfully.")


@router.get("/users", response_class=HTMLResponse)
def manage_users(request: Request, db: Session = Depends(get_db), current=Depends(require_admin)):
    users = db.query(User).order_by(User.username).all()
    return templates.TemplateResponse(request, "auth/users.html",
        {"request": request, "users": users, "current_user": current, "roles": list(UserRole), "error": None},
    )


@router.post("/users", response_class=HTMLResponse)
def create_user(
    request: Request,
    username: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: UserRole = Form(...),
    db: Session = Depends(get_db),
    current=Depends(require_admin),
):
    service = AuthService(db)
    try:
        new_user = service.register_user(
            UserCreate(username=username, full_name=full_name, email=email, password=password, role=role),
            created_by=current.id,
        )
    except AuthError as e:
        users = db.query(User).order_by(User.username).all()
        return templates.TemplateResponse(request, "auth/users.html",
            {"request": request, "users": users, "current_user": current, "roles": list(UserRole), "error": str(e)},
            status_code=400,
        )
    return redirect_with_flash("/users", f"User '{new_user.username}' created successfully.")


@router.post("/users/{user_id}/deactivate")
def deactivate_user(user_id: int, db: Session = Depends(get_db), current=Depends(require_admin)):
    service = AuthService(db)
    try:
        user = service.set_active_status(user_id, is_active=False, acting_user_id=current.id)
        return redirect_with_flash("/users", f"'{user.username}' has been deactivated.")
    except AuthError as e:
        return redirect_with_flash("/users", str(e), "danger")


@router.post("/users/{user_id}/reactivate")
def reactivate_user(user_id: int, db: Session = Depends(get_db), current=Depends(require_admin)):
    service = AuthService(db)
    try:
        user = service.set_active_status(user_id, is_active=True, acting_user_id=current.id)
        return redirect_with_flash("/users", f"'{user.username}' has been reactivated.")
    except AuthError as e:
        return redirect_with_flash("/users", str(e), "danger")


@router.post("/users/{user_id}/delete")
def delete_user(user_id: int, db: Session = Depends(get_db), current=Depends(require_admin)):
    service = AuthService(db)
    try:
        user = db.query(User).filter(User.id == user_id).first()
        username = user.username if user else "User"
        service.delete_user(user_id, acting_user_id=current.id)
        return redirect_with_flash("/users", f"'{username}' has been permanently deleted.")
    except AuthError as e:
        return redirect_with_flash("/users", str(e), "danger")

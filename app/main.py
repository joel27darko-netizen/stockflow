"""
StockFlow — Inventory & Warehouse Management System
Application entrypoint: creates the FastAPI app, mounts static files,
registers routers, sets up logging, and bootstraps the database.
"""
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.logging_config import configure_logging
from app.database import Base, engine, SessionLocal
from app.routers import (
    auth_router,
    dashboard_router,
    product_router,
    warehouse_router,
    inventory_router,
    reports_router,
    audit_router,
)
from app.services.auth_service import AuthService

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="StockFlow", description="Inventory & Warehouse Management System")
templates = Jinja2Templates(directory="app/templates")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router.router)
app.include_router(dashboard_router.router)
app.include_router(product_router.router)
app.include_router(warehouse_router.router)
app.include_router(inventory_router.router)
app.include_router(reports_router.router)
app.include_router(audit_router.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Handles all HTTPException cases:
      - 303 with a Location header: raised by auth dependencies when the
        user isn't logged in, so browser navigation redirects to /login
        instead of showing a raw JSON error.
      - 404: rendered as a friendly page for browser navigation, or a
        plain JSON response for API-style/AJAX requests.
      - Anything else (403, 400, etc.): friendly HTML page for normal
        page loads, JSON for API-style requests.
    """
    if exc.status_code == 303 and "Location" in (exc.headers or {}):
        return RedirectResponse(exc.headers["Location"], status_code=303)

    wants_json = "application/json" in request.headers.get("accept", "")
    if wants_json:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    try:
        return templates.TemplateResponse(request, "errors/error.html",
            {"request": request, "code": exc.status_code, "current_user": None},
            status_code=exc.status_code,
        )
    except Exception:
        # If template rendering itself fails for any reason, fall back
        # to a plain response rather than crashing the error handler.
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handles malformed form submissions (e.g. a required dropdown left
    unselected, a non-numeric value in a numeric field) with a friendly
    message instead of FastAPI's default raw JSON error dump. Since
    every form in this app already has client-side `required`
    attributes, this is primarily a defensive fallback for anyone
    bypassing the browser (or a browser quirk with autofill/back-button
    resubmission).
    """
    logger.warning("Validation error on %s %s: %s", request.method, request.url.path, exc.errors())

    wants_json = "application/json" in request.headers.get("accept", "")
    if wants_json:
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    referer = request.headers.get("referer", "/dashboard")
    from urllib.parse import quote
    message = quote("Please check the form — one or more fields were missing or invalid.")
    separator = "&" if "?" in referer else "?"
    return RedirectResponse(f"{referer}{separator}flash={message}&flash_type=danger", status_code=303)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Last-resort safety net for anything that isn't an expected
    HTTPException — a bug, an unexpected DB error, etc. Logs the full
    traceback server-side (so it's debuggable) but shows the user a
    calm, generic error page instead of a raw Python stack trace.
    """
    logger.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    return templates.TemplateResponse(request, "errors/error.html",
        {"request": request, "code": 500, "current_user": None},
        status_code=500,
    )


@app.on_event("startup")
def on_startup():
    logger.info("Starting StockFlow application...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        AuthService(db).ensure_default_admin()
    finally:
        db.close()
    logger.info("Startup complete. Database ready.")


@app.get("/health")
def health_check():
    return {"status": "ok", "app": "StockFlow"}


@app.get("/{full_path:path}", include_in_schema=False)
async def catch_all_not_found(request: Request, full_path: str):
    """
    Starlette's router returns a bare 'Not Found' response directly for
    any path that doesn't match a registered route — it never raises an
    HTTPException, so the exception_handler above never gets a chance
    to run for these. Registering this catch-all LAST (after every real
    router is included) means it only ever matches genuinely unmatched
    paths, and lets us render the same friendly 404 page instead of a
    bare text response.
    """
    return templates.TemplateResponse(request, "errors/error.html", {"request": request, "code": 404, "current_user": None}, status_code=404
    )

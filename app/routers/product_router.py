from typing import Optional

from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.flash import redirect_with_flash
from app.database import get_db
from app.dependencies import require_any_role, require_manager_or_admin
from app.schemas.product import ProductCreate, ProductUpdate, CategoryCreate
from app.services.product_service import ProductService, ProductServiceError
from app.services.product_import_service import ProductImportService, BulkImportError

router = APIRouter(prefix="/products", tags=["products"])
templates = Jinja2Templates(directory="app/templates")


def _build_query_string(q: str, category_id: Optional[int], low_stock_only: bool, page: Optional[int] = None) -> str:
    """Preserves current filters across pagination links and form resubmission."""
    params = []
    if q:
        params.append(f"q={q}")
    if category_id:
        params.append(f"category_id={category_id}")
    if low_stock_only:
        params.append("low_stock_only=true")
    if page:
        params.append(f"page={page}")
    return "&".join(params)


@router.get("", response_class=HTMLResponse)
def list_products(
    request: Request,
    q: Optional[str] = None,
    category_id: Optional[str] = None,
    low_stock_only: bool = False,
    page: int = 1,
    db: Session = Depends(get_db),
    current=Depends(require_any_role),
):
    # category_id arrives as a raw query string on purpose: the "All
    # Categories" <option value=""> submits an EMPTY STRING, not an
    # absent parameter. Typing this as Optional[int] directly makes
    # FastAPI reject "" with a 422 validation error before this function
    # ever runs — which is exactly the "category search doesn't work"
    # bug. Parsing it manually here treats "" the same as "not selected".
    category_id_int: Optional[int] = None
    if category_id and category_id.strip().isdigit():
        category_id_int = int(category_id)

    service = ProductService(db)
    result = service.search_products(
        query=q, category_id=category_id_int, low_stock_only=low_stock_only, page=page
    )
    categories = service.list_categories()
    has_any_products = bool(service.repo.count_search(is_active=None))

    return templates.TemplateResponse(request, "products/list.html",
        {
            "request": request, "result": result, "categories": categories,
            "current_user": current, "q": q or "", "category_id": category_id_int,
            "low_stock_only": low_stock_only, "has_any_products": has_any_products,
            "querystring": _build_query_string(q or "", category_id_int, low_stock_only),
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_product_form(request: Request, db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    categories = ProductService(db).list_categories()
    return templates.TemplateResponse(request, "products/form.html",
        {"request": request, "product": None, "categories": categories, "current_user": current, "error": None},
    )


@router.post("/new", response_class=HTMLResponse)
def create_product(
    request: Request,
    product_code: str = Form(""),
    name: str = Form(...),
    description: str = Form(""),
    category_id: Optional[int] = Form(None),
    price: float = Form(...),
    reorder_level: int = Form(10),
    db: Session = Depends(get_db),
    current=Depends(require_manager_or_admin),
):
    service = ProductService(db)
    try:
        data = ProductCreate(
            product_code=product_code, name=name, description=description,
            category_id=category_id, price=price, reorder_level=reorder_level,
        )
        product = service.create_product(data, current.id)
    except ProductServiceError as e:
        categories = service.list_categories()
        return templates.TemplateResponse(request, "products/form.html",
            {"request": request, "product": None, "categories": categories, "current_user": current, "error": str(e)},
            status_code=400,
        )
    except ValueError as e:
        # Pydantic validation errors (e.g. bad price format slipping past HTML validation)
        categories = service.list_categories()
        return templates.TemplateResponse(request, "products/form.html",
            {"request": request, "product": None, "categories": categories, "current_user": current,
             "error": f"Please check your input: {e}"},
            status_code=400,
        )
    was_auto_generated = not product_code.strip()
    flash_msg = (
        f"Product created with auto-generated code '{product.product_code}'."
        if was_auto_generated
        else f"Product '{product.product_code}' created successfully."
    )
    return redirect_with_flash("/products", flash_msg)


@router.get("/categories/manage", response_class=HTMLResponse)
def manage_categories(request: Request, db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    service = ProductService(db)
    return templates.TemplateResponse(request, "products/categories.html",
        {"request": request, "categories": service.list_categories(), "current_user": current, "error": None},
    )


@router.post("/categories/manage", response_class=HTMLResponse)
def create_category(
    request: Request, name: str = Form(...), description: str = Form(""),
    db: Session = Depends(get_db), current=Depends(require_manager_or_admin),
):
    service = ProductService(db)
    try:
        category = service.create_category(CategoryCreate(name=name, description=description), current.id)
    except ProductServiceError as e:
        return templates.TemplateResponse(request, "products/categories.html",
            {"request": request, "categories": service.list_categories(), "current_user": current, "error": str(e)},
            status_code=400,
        )
    return redirect_with_flash("/products/categories/manage", f"Category '{category.name}' added successfully.")


@router.get("/import", response_class=HTMLResponse)
def import_products_form(request: Request, db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    return templates.TemplateResponse(request, "products/import.html", {"request": request, "current_user": current, "error": None, "result": None}
    )


@router.post("/import", response_class=HTMLResponse)
async def import_products_submit(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current=Depends(require_manager_or_admin),
):
    if not file.filename:
        return templates.TemplateResponse(request, "products/import.html",
            {"request": request, "current_user": current, "error": "Please choose a file to upload.", "result": None},
            status_code=400,
        )

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        return templates.TemplateResponse(request, "products/import.html",
            {"request": request, "current_user": current, "error": "The uploaded file is empty.", "result": None},
            status_code=400,
        )
    if len(file_bytes) > 5 * 1024 * 1024:  # 5 MB
        return templates.TemplateResponse(request, "products/import.html",
            {"request": request, "current_user": current,
             "error": "File is too large (max 5 MB). Split it into smaller batches.", "result": None},
            status_code=400,
        )

    service = ProductImportService(db)
    try:
        result = service.import_file(file_bytes, file.filename, current.id)
    except BulkImportError as e:
        return templates.TemplateResponse(request, "products/import.html",
            {"request": request, "current_user": current, "error": str(e), "result": None},
            status_code=400,
        )

    return templates.TemplateResponse(request, "products/import.html",
        {"request": request, "current_user": current, "error": None, "result": result},
    )


@router.get("/import/template.csv")
def download_import_template(current=Depends(require_manager_or_admin)):
    template_content = (
        "product_code,name,description,category,price,reorder_level\n"
        "SKU-1001,Sample Widget,A short description,Electronics,9.99,10\n"
        ",Another Item (auto-generates a code),,Office Supplies,4.50,5\n"
    )
    return StreamingResponse(
        iter([template_content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=stockflow_import_template.csv"},
    )


@router.get("/{product_id}", response_class=HTMLResponse)
def product_detail(product_id: int, request: Request, db: Session = Depends(get_db), current=Depends(require_any_role)):
    service = ProductService(db)
    product = service.get_product(product_id)
    if not product:
        return redirect_with_flash("/products", "That product could not be found — it may have been deleted.", "danger")
    from app.services.inventory_service import InventoryService
    inv_items = InventoryService(db).get_inventory_for_product(product_id)
    return templates.TemplateResponse(request, "products/detail.html",
        {"request": request, "product": product, "inventory_items": inv_items, "current_user": current},
    )


@router.get("/{product_id}/edit", response_class=HTMLResponse)
def edit_product_form(
    product_id: int, request: Request, db: Session = Depends(get_db), current=Depends(require_manager_or_admin)
):
    service = ProductService(db)
    product = service.get_product(product_id)
    if not product:
        return redirect_with_flash("/products", "That product could not be found — it may have been deleted.", "danger")
    categories = service.list_categories()
    return templates.TemplateResponse(request, "products/form.html",
        {"request": request, "product": product, "categories": categories, "current_user": current, "error": None},
    )


@router.post("/{product_id}/edit", response_class=HTMLResponse)
def update_product(
    product_id: int,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    category_id: Optional[int] = Form(None),
    price: float = Form(...),
    reorder_level: int = Form(10),
    is_active: bool = Form(True),
    db: Session = Depends(get_db),
    current=Depends(require_manager_or_admin),
):
    service = ProductService(db)
    try:
        data = ProductUpdate(
            name=name, description=description, category_id=category_id,
            price=price, reorder_level=reorder_level, is_active=is_active,
        )
        product = service.update_product(product_id, data, current.id)
    except ProductServiceError as e:
        product = service.get_product(product_id)
        categories = service.list_categories()
        return templates.TemplateResponse(request, "products/form.html",
            {"request": request, "product": product, "categories": categories, "current_user": current, "error": str(e)},
            status_code=400,
        )
    return redirect_with_flash(f"/products/{product_id}", f"Product '{product.product_code}' updated successfully.")


@router.post("/{product_id}/delete")
def delete_product(product_id: int, db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    service = ProductService(db)
    try:
        product = service.get_product(product_id)
        code = product.product_code if product else "Product"
        service.delete_product(product_id, current.id)
        return redirect_with_flash("/products", f"'{code}' was deleted successfully.")
    except ProductServiceError as e:
        return redirect_with_flash("/products", str(e), "danger")


@router.post("/{product_id}/image")
async def upload_product_image(
    product_id: int, image: UploadFile = File(...),
    db: Session = Depends(get_db), current=Depends(require_manager_or_admin),
):
    service = ProductService(db)
    if not image.filename:
        return redirect_with_flash(f"/products/{product_id}", "Please choose an image file to upload.", "danger")

    file_bytes = await image.read()
    try:
        service.set_product_image(product_id, file_bytes, image.content_type or "", current.id)
    except ProductServiceError as e:
        return redirect_with_flash(f"/products/{product_id}", str(e), "danger")
    return redirect_with_flash(f"/products/{product_id}", "Product image updated successfully.")


@router.post("/{product_id}/image/remove")
def remove_product_image(product_id: int, db: Session = Depends(get_db), current=Depends(require_manager_or_admin)):
    service = ProductService(db)
    try:
        service.remove_product_image(product_id, current.id)
    except ProductServiceError as e:
        return redirect_with_flash(f"/products/{product_id}", str(e), "danger")
    return redirect_with_flash(f"/products/{product_id}", "Product image removed.")



"""
HTTP-level tests via FastAPI's TestClient.

These exist specifically because two real bugs in this project were
routing-layer issues that service-level unit tests couldn't have
caught: (1) an empty-string query param ("All Categories") triggering
a FastAPI validation error instead of "no filter", and (2) a literal
path segment ("/products/import") being shadowed by an earlier
parameterized route ("/products/{product_id}"). Both classes of bug
only show up when you actually make an HTTP request through the real
route table — hence testing at this level in addition to the service
layer.
"""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def client(monkeypatch):
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # main.py's startup event calls Base.metadata.create_all(bind=engine)
    # and SessionLocal() using names it imported directly at module load
    # time — patching app.database.engine after the fact wouldn't affect
    # those already-bound references in app.main, so we patch app.main's
    # own module-level names instead. Without this, the startup event
    # (which bootstraps the default admin account) would silently run
    # against the real stockflow.db instead of this test's temp database.
    import app.main as main_module
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(main_module, "SessionLocal", TestSessionLocal)

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    os.remove(db_path)


def _login(client: TestClient) -> None:
    client.get("/login")
    resp = client.post("/login", data={"username": "admin", "password": "Admin@123"}, follow_redirects=False)
    assert resp.status_code == 303

    # The bootstrapped default admin has must_change_password=True, so
    # every other route would otherwise redirect to /change-password.
    # Complete that step here once, so the rest of each test's requests
    # behave like a normal, already-onboarded session.
    change_resp = client.post(
        "/change-password",
        data={
            "current_password": "Admin@123",
            "new_password": "NewAdminPass123",
            "confirm_password": "NewAdminPass123",
        },
        follow_redirects=False,
    )
    assert change_resp.status_code == 303


def test_products_all_categories_filter_does_not_422(client):
    """The exact bug: selecting 'All Categories' submits category_id=''"""
    _login(client)
    resp = client.get("/products?category_id=&q=&low_stock_only=false")
    assert resp.status_code == 200
    assert "Products" in resp.text


def test_products_with_actual_category_filter_works(client):
    _login(client)
    client.post("/products/categories/manage", data={"name": "Electronics", "description": ""})
    client.post("/products/new", data={
        "product_code": "SKU-1", "name": "Widget", "description": "",
        "category_id": "1", "price": "9.99", "reorder_level": "5",
    })
    resp = client.get("/products?category_id=1")
    assert resp.status_code == 200
    assert "SKU-1" in resp.text


def test_products_import_route_is_reachable_not_shadowed(client):
    """The exact bug: /products/import was being swallowed by /products/{product_id}"""
    _login(client)
    resp = client.get("/products/import")
    assert resp.status_code == 200
    assert "Bulk Import" in resp.text


def test_products_import_template_download_reachable(client):
    _login(client)
    resp = client.get("/products/import/template.csv")
    assert resp.status_code == 200
    assert "product_code" in resp.text


def test_transactions_all_products_filter_does_not_422(client):
    _login(client)
    resp = client.get("/inventory/transactions?product_id=&transaction_type=")
    assert resp.status_code == 200


def test_my_activity_page_loads(client):
    _login(client)
    resp = client.get("/inventory/my-activity")
    assert resp.status_code == 200
    assert "My Activity" in resp.text


def test_my_activity_only_shows_current_users_own_transactions(client):
    """
    Scoping is enforced server-side by performed_by == current.id — this
    test creates a transaction as admin and confirms it shows up on
    admin's own activity page (the negative case — a second user seeing
    admin's transactions — would require a second login session, but the
    query itself is proven scoped in test_inventory_service.py at the
    service layer; this confirms the route wires it through correctly).
    """
    _login(client)
    client.post("/warehouses/new", data={"name": "Main WH", "address": ""})
    client.post("/warehouses/locations/new", data={"warehouse_id": "1", "zone": "A", "shelf": "", "notes": ""})
    client.post("/products/new", data={
        "product_code": "SKU-1", "name": "Widget", "description": "",
        "category_id": "", "price": "9.99", "reorder_level": "5",
    })
    client.post("/inventory/stock-in", data={
        "product_id": "1", "location_id": "1", "quantity": "10", "reference": "", "notes": "",
    })
    resp = client.get("/inventory/my-activity")
    assert resp.status_code == 200
    assert "SKU-1" in resp.text


def test_warehouse_deactivate_and_reactivate_via_http(client):
    _login(client)
    client.post("/warehouses/new", data={"name": "Main WH", "address": ""})
    resp = client.post("/warehouses/1/deactivate", follow_redirects=True)
    assert resp.status_code == 200
    assert "deactivated" in resp.text.lower()

    resp = client.post("/warehouses/1/reactivate", follow_redirects=True)
    assert resp.status_code == 200
    assert "reactivated" in resp.text.lower()


def test_404_page_is_friendly_not_raw_json(client):
    _login(client)
    resp = client.get("/this-does-not-exist")
    assert resp.status_code == 404
    assert "Page Not Found" in resp.text


def test_dashboard_loads_with_chart_containers(client):
    _login(client)
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "movementChart" in resp.text
    assert "categoryChart" in resp.text

# StockFlow — Inventory & Warehouse Management System

StockFlow is a full-stack inventory and warehouse management system built with **FastAPI**, **SQLAlchemy**, and **Jinja2 + Bootstrap 5**. It was built as a portfolio project to demonstrate backend architecture, database design, and full-stack delivery skills relevant to  Computer Science / System Integration** application.

> Portfolio note: this project focuses on demonstrating clean architecture (Repository Pattern + Service Layer), concurrency-safe business logic, and end-to-end feature delivery — from database schema to a working, polished browser UI — rather than an exhaustive production feature set.

---

## Table of Contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Project Structure](#project-structure)
4. [Setup Instructions](#setup-instructions)
5. [Default Login](#default-login)
6. [Running Tests](#running-tests)
7. [Database Migrations (Alembic)](#database-migrations-alembic)
8. [Screenshots](#screenshots)
9. [Scalability & System Design Notes](#scalability--system-design-notes)
10. [Known Limitations / Next Steps](#known-limitations--next-steps)

---

## Features

### Authentication & Authorization
- Session-based login using a signed JWT stored in an httponly cookie
- Three roles — **Admin**, **Warehouse Manager**, **Staff** — enforced via FastAPI dependencies
- Admin-only user management (create, deactivate/reactivate, permanently delete)
- **Forced password change on first login** for every account, including the bootstrapped default admin — a dependency-level check redirects any other request until it's resolved
- **Rate-limited login** — 5 failed attempts per (username, IP) locks that pair out for 5 minutes
- "Remember me" genuinely extends the session (30 days vs. the default 8 hours), not just cosmetic

### Product Management
- Full CRUD: product code, name, category, description, price, reorder level
- **Auto-generated product codes** (`SKU-00001`, `SKU-00002`, ...) — leave the code field blank and StockFlow generates a unique one; enter your own and it's validated for uniqueness instead. Works the same way in bulk import: a blank `product_code` cell (or an entirely missing column) auto-generates per row, with no collisions even across multiple blank rows in the same file
- Category management
- Optional product photo upload, validated and resized server-side via Pillow
- Automatic **QR code** and **Code128 barcode** generation on product creation
- Bulk import from **CSV or Excel (.xlsx)**, with per-row error isolation (one bad row doesn't fail the whole batch) and a downloadable template
- List view and card view (with photo + QR thumbnail), plus an instant client-side quick filter on top of full server-side search

### Warehouse & Location Management
- Multiple warehouses, each with zones/shelves (`Location` model)
- Products are tracked per-location via an `InventoryItem` join table, so the same SKU can hold a different quantity at every shelf/warehouse
- Soft delete (deactivate/reactivate) for both warehouses and locations, with a guarded permanent-delete option that's blocked if transaction history exists

### Inventory Operations
- **Stock In** — receive from a supplier, with a reference/invoice number
- **Stock Out** — issue/sale, validated against available quantity
- **Stock Adjustment** — correct to a physical count, with automatic delta calculation
- **Transfer** — move stock between locations as a single atomic operation, recorded as a linked pair of ledger entries sharing a common reference (e.g. `TRANSFER-28440B34`)
- Every operation writes an immutable `Transaction` ledger row (before/after quantities, unit price snapshot, performed-by user) — nothing is ever edited in place
- **Stock-out and transfer both use an atomic conditional SQL `UPDATE`** (`WHERE quantity >= X`), not a Python read-check-write — this closes a real race condition where two concurrent requests could both pass validation and oversell the same stock. Proven with a dedicated multi-threaded test (`tests/test_concurrency.py`), not just claimed

### Barcode / QR Scanning (Simulated)
- Scanner page requests webcam access to demonstrate the real integration point
- Resolves a scanned/typed code to a product via product code or barcode value — keeps the demo reliable in any environment without requiring a real barcode-decoding library or a physical label to test with

### Alerts & Audit
- Low-stock detection (`reorder_level` vs. total quantity across all locations), surfaced on the dashboard and a live notification bell
- Full transaction history with filtering by product/type, plus a personal **"My Activity"** view scoped to the logged-in user
- Separate `AuditLog` table capturing administrative actions (user changes, product edits, logins, bulk imports) — viewable by admins at `/audit-log`

### Dashboard
- KPI cards: total products, total inventory value, low-stock count, total units in stock
- Interactive charts (Chart.js): 14-day stock movement trend (in vs. out) and inventory value by category
- Recent transactions feed and quick-action buttons

### Reports
- CSV, Excel, and PDF export for products and transactions

### UI
- Sidebar navigation with icons, sticky topbar with profile dropdown and a real notification bell (backed by a small JSON endpoint, not decorative)
- Dark/light mode toggle, persisted per-browser, synced with Bootstrap 5's own native dark-mode CSS
- Confirmation modals instead of native browser `confirm()` popups, loading spinners on form submit, auto-dismissing flash messages
- Responsive layout (mobile off-canvas sidebar)

---

## Architecture

StockFlow follows a **layered architecture** to keep concerns separated and testable:

```
Router (FastAPI, Jinja2)
   → Service (business logic, validation, orchestration)
      → Repository (data access, SQLAlchemy queries)
         → Model (SQLAlchemy ORM)
```

- **Routers** (`app/routers/`) only handle HTTP concerns: parsing form/query input, calling a service, and rendering a template or redirect. No business logic lives here.
- **Services** (`app/services/`) own business rules — e.g. "you cannot stock-out more than what's available," "a product code must be unique," "creating a product also generates its QR/barcode and, if none was given, its code." Services raise domain-specific exceptions (`InventoryServiceError`, `ProductServiceError`, `AuthError`, ...) that routers translate into user-facing messages.
- **Repositories** (`app/repositories/`) are the only layer that talks to SQLAlchemy `Session` objects directly. A generic `BaseRepository` provides CRUD; concrete repositories add domain queries (search, filters, natural-key lookups).
- **Schemas** (`app/schemas/`) are Pydantic models used for input validation, decoupled from the SQLAlchemy models so the API/DB shape can evolve independently.
- **Models** (`app/models/`) are the SQLAlchemy ORM definitions and the source of truth for the schema, used by Alembic autogeneration.

This separation is what lets the concurrency-critical logic in `InventoryService` be unit-tested directly — including with real threads — without a running HTTP server anywhere in the test.

### Data Model Overview

```
User ──< Transaction >── Product ──< InventoryItem >── Location >── Warehouse
                                    Product >── Category
User ──< AuditLog
```

- `Product` ←→ `InventoryItem` ←→ `Location`: many-to-many via `InventoryItem`, which is how a single product can have different quantities across different shelves/warehouses.
- `Transaction`: an append-only ledger. Quantities are never mutated in place without a corresponding transaction row — this is what allows accurate audit trails and historical reporting. `InventoryItem.quantity` is fast-to-read current state; `Transaction` is permanent history.

---

## Project Structure

```
stockflow/
├── app/
│   ├── core/                # config, logging, security (hashing/JWT), rate limiter, flash messages
│   ├── models/               # SQLAlchemy ORM models
│   ├── schemas/                # Pydantic request/response schemas
│   ├── repositories/            # Data-access layer
│   ├── services/                  # Business logic layer
│   ├── routers/                     # FastAPI route handlers (HTTP + Jinja2 rendering)
│   ├── templates/                     # Jinja2 templates (Bootstrap 5, sidebar layout, dark mode)
│   ├── static/                          # CSS, JS, generated QR/barcode/product images
│   ├── database.py                        # Engine/session/Base
│   ├── dependencies.py                      # Auth/role dependencies, forced-password-change gate
│   └── main.py                                # App entrypoint, exception handlers
├── alembic/                    # DB migrations (3 revisions)
├── tests/                       # Pytest suite — 73 tests across 10 files
├── requirements.txt
├── alembic.ini
├── pytest.ini
├── .env.example
└── README.md
```

---

## Setup Instructions

### Prerequisites
- Python 3.11 or 3.12 (Python 3.14 is too new — several dependencies don't yet ship prebuilt wheels for it and will fail to compile)
- pip

### 1. Clone and install dependencies

```bash
git clone <your-repo-url> stockflow
cd stockflow
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and set a real SECRET_KEY for anything beyond local development
```

### 3. Run the application

```bash
uvicorn app.main:app --reload
```

The app creates its SQLite database and a default admin account automatically on first startup (see below). Visit **http://127.0.0.1:8000**.

### 4. First-login walkthrough

1. Log in with the [default admin credentials](#default-login) — you'll immediately be asked to set a new password (forced on every account's first login).
2. Go to **Products → Categories** and add at least one category.
3. Go to **Warehouses** and add a warehouse plus at least one zone/shelf.
4. Go to **Products → New Product** — try leaving the Product Code field blank to see it auto-generate one, or enter your own.
5. Go to **Stock Ops** to record a Stock In, then try a Stock Out, Adjustment, or Transfer between locations.
6. Check the **Dashboard** for live metrics and charts, and the **Reports** page for CSV/Excel/PDF exports.

---

## Default Login

On first startup, StockFlow bootstraps a default administrator:

| Username | Password    |
|----------|-------------|
| `admin`  | `Admin@123` |

**You'll be required to set a new password immediately on first login** — every account in StockFlow (this bootstrapped admin, and any user an admin creates) starts with `must_change_password = True`. The app redirects any other request until that's resolved, so there's no way to accidentally leave a default password active.

---

## Running Tests

The bulk of the test suite exercises the **service layer** directly against an **in-memory SQLite** database (via `StaticPool`), so most tests run fast and never touch `stockflow.db`. A smaller set (`test_http_routes.py`) exercises real HTTP routes end-to-end via FastAPI's `TestClient`, and `test_concurrency.py` uses real threads against a temporary file-backed SQLite database specifically to prove the stock-out race condition fix holds under actual concurrent load.

```bash
pip install pytest   # already in requirements.txt
pytest
```

**73 tests, all passing**, covering: authentication and forced password change, product CRUD and auto-generated codes, category uniqueness, the full stock-in/out/adjustment/transfer lifecycle (including insufficient-stock validation and low-stock detection), bulk CSV/Excel import (including per-row error isolation and code auto-generation), product image upload, warehouse/location soft delete, and a real multi-threaded concurrency test.

---

## Database Migrations (Alembic)

The project ships with Alembic configured (`alembic.ini`, `alembic/env.py`) and three migrations in `alembic/versions/`: initial schema, soft-delete + product images, and forced password change support.

```bash
# Apply migrations to bring a fresh database up to date
alembic upgrade head

# After changing a model, generate a new migration
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

In local development, `Base.metadata.create_all()` also runs on startup as a convenience so the app works immediately after `pip install`. In a real deployment you would rely on `alembic upgrade head` exclusively and drop the `create_all()` call.

Note: a couple of the migrations needed hand-adjustment after autogeneration — e.g. adding `server_default` values so a new `NOT NULL` column doesn't fail against a database that already has rows, and skipping an autogenerated `ALTER COLUMN` on an Enum type that SQLite doesn't meaningfully enforce anyway. Both are documented inline in the migration files themselves.

---

## Screenshots

> _Add screenshots here before submitting your portfolio. Suggested set:_

<img width="952" height="456" alt="Capture01" src="https://github.com/user-attachments/assets/ca6af205-3af6-4836-a9b2-fdfef43f7d6d" />
<img width="951" height="454" alt="Capture02" src="https://github.com/user-attachments/assets/8e57c2b4-42ec-4709-b9c1-047d77cddd29" />
<img width="954" height="453" alt="Capture03" src="https://github.com/user-attachments/assets/c7454f8d-6b57-4c97-b946-830ab55413e5" />
<img width="950" height="455" alt="Capture111" src="https://github.com/user-attachments/assets/882f0d16-ab19-4849-8a92-6551f9c74cbf" />
<img width="953" height="454" alt="Capture040" src="https://github.com/user-attachments/assets/c9250a4f-cf90-479e-8e13-0e7a962d2684" />
<img width="952" height="456" alt="Capture030" src="https://github.com/user-attachments/assets/9545b584-6c2b-43c4-b555-344d9be0aa4e" />
<img width="953" height="453" alt="Capture12" src="https://github.com/user-attachments/assets/f4dcee9a-0605-4e7e-8742-10addc644db6" />


---

## Scalability & System Design Notes

This section documents how the current design would evolve for production scale — useful talking points for interviews/assessment centers:

- **Database**: SQLite is used for portfolio simplicity and zero-setup grading. The Repository layer means switching to PostgreSQL is a one-line change to `DATABASE_URL` — no service or router code changes needed, since nothing above the repository layer knows or cares which database engine sits underneath.
- **Concurrency**: the stock-out and transfer atomic-update pattern (`UPDATE ... WHERE quantity >= X`) works correctly with SQLite today and is also the correct, portable pattern for PostgreSQL/MySQL under real concurrent load — no code changes needed if the database is swapped later.
- **Caching**: dashboard metrics currently recompute from the DB on every request. At scale, this would move to a cached read model (Redis) refreshed on write or a short TTL.
- **Rate limiting**: the login rate limiter is in-process memory today — correct for a single instance, but wouldn't share state across multiple server instances behind a load balancer. That would move to a shared store (Redis) for a true multi-instance deployment.
- **Background jobs**: QR/barcode/image generation currently happens synchronously in the request/response cycle. At higher volume this would move to a task queue (Celery/RQ) so product creation doesn't block on image I/O.
- **API-first evolution**: because Pydantic schemas already exist independently of the Jinja2 templates, adding a JSON API surface (for a future mobile app or external integration) alongside the server-rendered UI is additive, not a rewrite.
- **Multi-tenancy**: if StockFlow needed to serve multiple companies, a `tenant_id` column (or schema-per-tenant) would be added to core tables, with the repository layer updated to scope every query by tenant.

---

## Known Limitations / Next Steps

- Barcode/QR **scanning** is simulated via manual code entry rather than real-time camera frame decoding (would use a library like ZXing/`html5-qrcode` in a production build) — a deliberate choice to keep the demo reliable in any environment.
- No pagination on a few list views at real scale (e.g. warehouse/location lists) — fine for demo data volumes, would need `LIMIT`/`OFFSET` + UI controls before handling thousands of rows.
- No automated CI pipeline configured yet (tests are run locally via `pytest`).
- "Forgot password" is an honest simulation — there's no email/SMS infrastructure in this build, so rather than faking a reset-link flow that goes nowhere, it explains the real process (an admin resets it).

---



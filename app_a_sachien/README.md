# Application A — Smart Expense & Budget Manager

**Owner:** Sachien N · **Registration No:** 23MID0255 · **Computer:** Windows
**Course:** CSI3007 – Advanced Python Programming Project
**Stack:** Streamlit (frontend) · FastAPI (backend) · SQLAlchemy + Pydantic · SQLite (dev) / PostgreSQL (prod) · Plotly · Requests · pytest

Personal-finance dashboard with expense CRUD, transparent editable merchant→category
rules, monthly category budgets with utilization/overspending tracking, Plotly
charts, search/filter/pagination, CSV import/export, and **real REST integration**
with Application B (Subscription Tracker) and Application C (Electricity Manager).
It remains fully functional when a peer API is down.

---

## Features

| Area | Details |
|---|---|
| Expenses | Add / edit / delete / view; date, merchant, amount (`Numeric(12,2)` Decimal), ISO currency, category, payment method, description |
| Categories | Food, Travel, Bills, Entertainment, Shopping, Subscriptions, Other |
| Categorization rules | Editable pattern→category rules with priority (`GET/POST /rules`, `GET /categorize?merchant=Netflix`) |
| Budgets | Monthly per-category budget CRUD; utilization %, remaining, overspend alerts (`/budgets`, `/summary`) |
| Analytics | `GET /summary?month=YYYY-MM`: totals, per-category breakdown, budget status, external-source split; Plotly charts in the UI |
| Search & paging | `GET /expenses?page=&page_size=&search=&category=&source=&date_from=&date_to=&sort=` |
| CSV | `GET /export/csv`, `POST /import/csv` (per-row error reporting, auto-categorization fallback) |
| Integration B | `POST /sync/subscriptions` imports eligible recurring subscription costs idempotently |
| Integration C | `POST /sync/electricity` imports eligible electricity expense records idempotently |
| Idempotency | Unique DB constraint on `(source, external_id)` — repeated sync never duplicates records |
| Status | `GET /integration/status` (peer health + last successful sync), `GET /sync/history` |
| Security | Bearer token (`API_TOKEN`) protects all write endpoints; secrets only via environment variables |

## Repository layout

```
app.py                     # Streamlit frontend
main.py                    # FastAPI entry point
config.py database.py models.py schemas.py
api/                       # expenses.py budgets.py integration.py auth.py
services/                  # categorization.py budgets.py api_client.py sync_service.py
migrations/001_initial.sql # schema reference for PostgreSQL
tests/                     # pytest suite (17 tests)
requirements.txt requirements-dev.txt .env.example .gitignore
render.yaml pytest.ini
README.md DEPLOYMENT.md API_DOCUMENTATION.md TEST_REPORT.md TROUBLESHOOTING.md
```

## Local setup — Windows PowerShell (Sachien)

### 1. Install & verify Python

Install Python 3.11+ from https://www.python.org/downloads/ (**check “Add python.exe to PATH”**), then:

```powershell
python --version
pip --version
```

### 2. Create and activate a virtual environment

```powershell
cd C:\path\to\Sachien_Expense_Manager
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If activation is blocked, run once as Administrator:
`Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

### 3. Install dependencies

```powershell
pip install -r requirements-dev.txt
```

### 4. Configure environment variables

```powershell
Copy-Item .env.example .env
notepad .env    # set API_TOKEN (generate: python -c "import secrets; print(secrets.token_urlsafe(32))")
$env:DATABASE_URL = "sqlite:///./expense_manager.db"   # local dev default
$env:API_TOKEN    = "your-generated-token"
$env:EXPENSE_API_TOKEN = $env:API_TOKEN                # so the frontend can write
```

Peer URLs (`SUBSCRIPTION_API_URL`, `ELECTRICITY_API_URL`) stay empty until Apps B/C
are deployed — the app works without them.

### 5. Initialize the database

SQLite is created automatically on first start (`Base.metadata.create_all`).
For PostgreSQL instead, apply `migrations/001_initial.sql` with `psql`.

### 6. Start the backend (terminal 1)

```powershell
uvicorn main:app --reload --port 8001
```

API docs: http://localhost:8001/docs · Health: http://localhost:8001/health

### 7. Start the frontend (terminal 2)

```powershell
.\venv\Scripts\Activate.ps1
$env:EXPENSE_API_URL = "http://localhost:8001"   # development only
streamlit run app.py                              # opens http://localhost:8501
```

> Local ports are for development only. Production uses public HTTPS URLs (§ DEPLOYMENT.md).

### 8. Run the tests

```powershell
pytest -v
```

Expected: **17 passed**.

## Quick smoke test

```powershell
curl http://localhost:8001/health
curl "http://localhost:8001/categorize?merchant=Netflix"
curl -X POST http://localhost:8001/expenses -H "Content-Type: application/json" -H "Authorization: Bearer your-generated-token" -d '{\"expense_date\":\"2026-10-27\",\"merchant\":\"Zomato\",\"amount\":450.5,\"category\":\"Food\"}'
```

## Deployment

See **DEPLOYMENT.md** (Streamlit Community Cloud → frontend, Render free tier →
backend, Neon → PostgreSQL). API contract details: **API_DOCUMENTATION.md**.
Verified test results: **TEST_REPORT.md**. Common errors: **TROUBLESHOOTING.md**.

## Privacy note

The deployed website and API are **public**. Anyone who knows the URL can read
expense data served by unauthenticated GET endpoints. Do not store sensitive
personal information; keep `API_TOKEN` secret and rotate it if leaked.

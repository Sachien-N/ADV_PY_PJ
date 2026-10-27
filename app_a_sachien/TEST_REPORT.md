# Application A — Test Report

**Project:** Smart Expense & Budget Manager · **Owner:** Sachien N (23MID0255)
**Executed:** 2026-10-27 · Python 3.12 · pytest · FastAPI `TestClient` · SQLite in-memory/temp DB
**Command:** `pytest -v` → **Result: 17 passed, 0 failed, 0 skipped, 0 errors (0.77 s)**

## Automated unit / API tests (all PASSED)

| # | Test | Area verified | Status |
|---|------|---------------|--------|
| 1 | `test_health` | `GET /health` returns ok payload | ✅ Passed |
| 2 | `test_expense_crud_cycle` | POST→GET→PUT→DELETE full cycle, status codes 201/200/204 | ✅ Passed |
| 3 | `test_validation_errors` | Pydantic rejects negative/zero amounts, bad dates, unknown categories (422), missing expense (404) | ✅ Passed |
| 4 | `test_pagination_and_filters` | page/page_size bounds, search, category, source, date range filters, total counts | ✅ Passed |
| 5 | `test_categorization_rules` | Default rules (`Netflix→Subscriptions`), editable rule upsert/delete, priority ordering | ✅ Passed |
| 6 | `test_budget_utilization_and_overspending` | Utilization %, remaining amount, overspent flag with Decimal precision | ✅ Passed |
| 7 | `test_duplicate_budget_rejected` | Same month+category budget → 409 | ✅ Passed |
| 8 | `test_summary_month` | `/summary` totals, per-category breakdown, external-source split, month format validation | ✅ Passed |
| 9 | `test_csv_export_import_roundtrip` | Export CSV → re-import → row counts and per-line error reporting | ✅ Passed |
| 10 | `test_categories_endpoint_for_peers` | `GET /categories` contract used by Apps B/C | ✅ Passed |
| 11 | `test_sync_subscriptions_imports_and_idempotent` | Mocked App B; first sync imports, second sync creates **no duplicates** (skipped only) | ✅ Passed |
| 12 | `test_sync_updates_budget_summary` | Imported subscription cost changes `/summary` Subscriptions total correctly | ✅ Passed |
| 13 | `test_sync_electricity_only_eligible_records` | Mocked App C; only eligible expense records imported; estimates vs actuals distinguished | ✅ Passed |
| 14 | `test_peer_api_down_app_remains_functional` | ConnectionError from peer → sync returns unavailable status; CRUD unaffected | ✅ Passed |
| 15 | `test_invalid_external_payload_records_skipped` | Malformed peer JSON rows counted as skipped, never inserted | ✅ Passed |
| 16 | `test_integration_status_reports_unconfigured_peers` | `/integration/status` shows not-configured peers without crashing | ✅ Passed |
| 17 | `test_auth_required_for_writes_when_token_set` | Missing bearer token → 401 on POST/PUT/DELETE; valid token → success | ✅ Passed |

## Manual verification performed in this environment

| Check | Result |
|---|---|
| `uvicorn main:app` boots cleanly (lifespan init, tables created) | ✅ |
| `GET /health` over real HTTP server | ✅ `{"status":"ok","app":"expense-manager",...}` |
| `GET /docs` Swagger UI | ✅ HTTP 200 |
| `GET /categories`, `GET /categorize?merchant=Netflix`, `GET /summary?month=2026-10` | ✅ correct payloads |
| `app.py` syntax/import check | ✅ |

## Not executed here (requires owner action — see DEPLOYMENT.md)

- ❌ **Public deployment checks** (`/health` + `/docs` on a public HTTPS Render URL, Streamlit Cloud site): needs Sachien's GitHub/Render/Neon/Streamlit accounts — cannot be done by the build agent.
- ❌ **Live cross-app integration workflow** (steps 1–11 of the acceptance criteria against real Apps B & C URLs): requires Apps B and C to be deployed publicly; currently covered by mocked-API tests (#11–#15).
- ❌ **Persistence after restart on production PostgreSQL**: local SQLite persistence is exercised by the test fixtures; Neon persistence must be verified post-deployment (checklist step in DEPLOYMENT.md Part 3.7).

## Known limitations / open issues

1. Free-tier cold starts (Render) can make the first sync click time out at 10 s — increase `HTTP_TIMEOUT_SECONDS` or retry; bounded retries are already implemented.
2. `ALLOW_UNAUTHENTICATED_WRITES=1` exists for convenience/testing only — must never be set in production (documented in `.env.example`).
3. Alembic migration scripts beyond `001_initial.sql` are not generated; schema evolution relies on documented manual steps.

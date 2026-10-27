# Application A — Troubleshooting

## Local development (Windows PowerShell)

| Symptom | Cause | Fix |
|---|---|---|
| `python : The term 'python' is not recognized` | Python not installed or PATH missing | Reinstall from python.org with **“Add python.exe to PATH”** checked; reopen PowerShell |
| `Activation resulted in a error ... execution policy` | PowerShell script blocking | `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` (Admin), then re-activate venv |
| `pip install` fails compiling `psycopg2` | Windows lacks build tools for source wheel | Use `psycopg2-binary` (already pinned in requirements.txt); if using conda/older pip: `pip install --upgrade pip` |
| `Address already in use: 8001` / `8501` | Previous server still running | `Get-Process \| Where-Object {$_.ProcessName -like "*python*"}` → `Stop-Process -Id <pid>`; or change port |
| Frontend shows “Backend API unreachable” | Backend not running, or `EXPENSE_API_URL` wrong | Start `uvicorn main:app --reload --port 8001` first; check `$env:EXPENSE_API_URL = "http://localhost:8001"` |
| Frontend shows “Authentication failed” | `EXPENSE_API_TOKEN` ≠ backend `API_TOKEN` | Set both to the same value in every terminal session (or export from `.env`) |
| `401 Unauthorized` on POST from curl/PowerShell | Missing bearer header | Add `-H "Authorization: Bearer $env:API_TOKEN"`; note PowerShell `curl` is an alias — use `curl.exe` for real curl |
| `sqlite3.OperationalError: unable to open database file` | Read-only folder / bad path | Run from the project directory; default path is `./expense_manager.db` |
| Tests fail with `ModuleNotFoundError: api` | Running pytest from wrong directory | `cd` into the project root (where `pytest.ini` lives) before `pytest` |
| Unicode errors printing ₹/💰 in console | Legacy Windows codepage | `chcp 65001` or run Streamlit in Windows Terminal |

## Backend behaviour

| Symptom | Cause | Fix |
|---|---|---|
| `422` on create expense | Validation: amount ≤ 0, >2 decimals, unknown category, bad date format | Check payload against schemas.py / `/docs` model examples |
| `409` creating budget | Same month+category already exists | Update existing budget (`PUT /budgets/{id}`) instead |
| Sync returns `{"status":"unavailable"}` | Peer URL empty or peer asleep/down | Configure `SUBSCRIPTION_API_URL`/`ELECTRICITY_API_URL`; expect cold starts on Render free tier — click again after ~30 s |
| Sync imports 0 records though peer is up | Peer has no eligible records yet, or token rejected by peer (401 logged as failure in `/sync/history`) | Verify token shared by teammate; check `/sync/history` message field |
| Duplicate import despite unique constraint | None expected — `(source, external_id)` DB constraint blocks it; second sync reports `skipped` | This is correct idempotent behaviour |
| App starts but writes are blocked with empty token | `API_TOKEN` unset and `ALLOW_UNAUTHENTICATED_WRITES` not set | Set `API_TOKEN` (production) — do not disable auth in production |

## Deployment (Render / Neon / Streamlit Cloud)

| Symptom | Cause | Fix |
|---|---|---|
| Render build: `ModuleNotFoundError: psycopg2` | Dependency not installed | Confirm `requirements.txt` includes `psycopg2-binary`; clear cache via **Clear build cache & deploy** |
| Render crash loop `MissingGreenlet` / connection errors | Using Neon **direct** endpoint with pooling limits, or URL missing `+psycopg2` | Use the **pooled** connection string and prefix `postgresql+psycopg2://` |
| `SSL required` error | Neon demands TLS | Keep `?sslmode=require` in `DATABASE_URL` |
| Data lost after redeploy | SQLite used on ephemeral Render disk | Production MUST use Neon `DATABASE_URL` (see DEPLOYMENT.md) |
| CORS error in browser console calling API | `CORS_ORIGINS` doesn't match exact frontend origin | Set `CORS_ORIGINS=https://<name>.streamlit.app` (no trailing slash) and restart service |
| First page load takes ~1 minute | Free-tier sleep/cold start | Normal; optionally add a free uptime pinger to `/health` |
| Streamlit app crashes: `KeyError: 'EXPENSE_API_URL'` | Secrets not configured | Add both keys under Streamlit **Settings → Secrets**; `_cfg()` handles absence gracefully now |
| Streamlit builds succeed but old code runs | Repo cached | **Settings → Restart app**; verify pushed commit appears in repo |
| Public site readable by strangers | Expected — GET endpoints are public by design | Keep only non-sensitive demo data; rotate `API_TOKEN` if abused |

## Still stuck?

1. Reproduce with `pytest -v` (isolates app logic from environment).
2. Check backend logs: Render → **Logs**, or local uvicorn console.
3. Query `GET /integration/status` and `GET /sync/history` for integration-specific failures.
4. Attach the failing request/response (with secrets redacted) when asking teammates/instructor.

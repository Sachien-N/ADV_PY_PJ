# Application A — Free Public Deployment Guide (Sachien N, 23MID0255)

Goal: a **public HTTPS website** + **public HTTPS API** + **persistent PostgreSQL**,
all on free tiers (target ₹0/month), working even when your laptop is off.

Architecture: `Streamlit Cloud (frontend)` → `Render web service (FastAPI)` → `Neon PostgreSQL`.

> ⚠️ Honest free-tier limits (verify on provider docs before starting — they change):
> - **Render free web services sleep after ~15 min idle**; first request has a cold start of ~30–60 s. Data is NOT lost because it lives in Neon.
> - **Neon free plan**: ~0.5 GB storage, limited compute hours per month — fine for this project.
> - **Streamlit Community Cloud**: free public apps; the app rebuilds from your GitHub repo.
> - SQLite must NOT be used on Render (its filesystem is ephemeral — data disappears on redeploy/sleep). Always use the Neon URL in production.
> - Render free Postgres (if you use it instead of Neon) is **deleted after 30 days** — do not rely on it long-term; Neon is preferred here.

---

## Part 1 — GitHub repository

1. Sign up / sign in at https://github.com.
2. **New repository** → name `Sachien_Expense_Manager` → **Public** (or Private if using paid Streamlit plan; Public is fine for free) → *Do not* add README (you already have one) → Create.
3. From the project folder in PowerShell:

```powershell
git init
git add .
git commit -m "Application A: Smart Expense & Budget Manager"
git branch -M main
git remote add origin https://github.com/<your-username>/Sachien_Expense_Manager.git
git push -u origin main
```

`.gitignore` already excludes `.env`, databases, `venv/`, caches. **Never push secrets.**

## Part 2 — Neon PostgreSQL (Database A)

1. Sign up free at https://neon.tech (GitHub login works).
2. **Create project** → name `expense-manager-db` → region closest to India (e.g. Singapore) → default settings.
3. In **Dashboard → Connection Details**, copy the **pooled** connection string, format:
   `postgresql://USER:PASSWORD@ep-xxx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`
4. Convert it for SQLAlchemy by adding the driver:
   `postgresql+psycopg2://USER:PASSWORD@ep-xxx-pooler.../neondb?sslmode=require`

## Part 3 — Deploy the FastAPI backend on Render

1. Sign up free at https://render.com (GitHub login).
2. **New + → Blueprint** → connect the `Sachien_Expense_Manager` repository. The included `render.yaml` pre-fills everything (`sachien-expense-api`, free plan, build `pip install -r requirements.txt`, start `uvicorn main:app --host 0.0.0.0 --port $PORT`).
3. In the dashboard's env-var prompts, set (**sync: false = you provide values**):

| Key | Value |
|---|---|
| `DATABASE_URL` | your Neon pooled URL (with `+psycopg2`) |
| `API_TOKEN` | generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `SUBSCRIPTION_API_URL` | leave empty for now (fill after Shravan deploys B) |
| `SUBSCRIPTION_API_TOKEN` | token Shravan shares with you securely |
| `ELECTRICITY_API_URL` | leave empty for now (fill after Hariharan deploys C) |
| `ELECTRICITY_API_TOKEN` | token Hariharan shares securely |
| `CORS_ORIGINS` | `https://<your-streamlit-app>.streamlit.app` |
| `LOG_LEVEL` | `INFO` |

4. **Apply** → wait for the build. Free tier may queue briefly.
5. **Migrations/schema:** on first boot the app runs `create_all`, which creates all tables
   in the empty Neon DB — safe for a fresh deployment. For later schema changes, apply SQL
   from `migrations/` manually via the Neon SQL Editor, or run alembic locally against the
   Neon URL (see requirements-dev.txt). Never drop/recreate in production.
6. **Verify (mandatory):**
   - `https://<service>.onrender.com/health` → `{"status":"ok",...}`
   - `https://<service>.onrender.com/docs` → Swagger UI loads
   - `GET /categories` returns the 7 categories.
7. **Persistence check:** POST an expense (with bearer token), then **Manual Deploy → Restart** and GET it again — it must still exist. This proves Neon persistence.

## Part 4 — Deploy the Streamlit frontend

1. Sign in at https://share.streamlit.io with your GitHub account.
2. **Add new app** → repository `Sachien_Expense_Manager`, branch `main`, **Main file path `app.py`**.
3. Under **Secrets** (Settings → Secrets) add:

```toml
EXPENSE_API_URL = "https://<your-backend>.onrender.com"
EXPENSE_API_TOKEN = "<same API_TOKEN as Render>"
```

Also create `~/.streamlit/secrets.toml` equivalents locally only if needed — the code reads
`os.environ` first and **falls back to `st.secrets` automatically** (already implemented in
`app.py` via the `_cfg()` helper), so setting Streamlit Secrets alone is sufficient.

4. Deploy → you get `https://<name>.streamlit.app` (public HTTPS).
5. Verify the dashboard loads charts, adds an expense, and shows integration status
   (“peers not configured” is normal until B/C are live).
6. Confirm `CORS_ORIGINS` on Render contains the exact final streamlit.app URL; redeploy backend if you change it.

## Part 5 — Team integration exchange

1. When Shravan's App B is live: set `SUBSCRIPTION_API_URL=https://<b-backend>.onrender.com` and paste the token he sends you (use a secret-sharing channel — Signal/1Password, **not** WhatsApp groups or email screenshots). Save & restart.
2. Do the same with Hariharan for `ELECTRICITY_API_URL`.
3. Tell both teammates **your** public URL so their apps can call `GET /categories`.
4. Click **Sync subscriptions** / **Sync electricity** in the UI; confirm imported rows show source `app_b_subscription` / `app_c_electricity`; click again → `skipped` increments, no duplicates.

## Part 6 — Ongoing operations

- **Update code:** `git add . && git commit -m "..." && git push`. Render auto-deploys from GitHub (Blueprint); Streamlit needs “Restart” or redeploys on push if configured.
- **Rotate a secret:** change the value in Render/Streamlit dashboards only — never commit it; inform affected teammates simultaneously.
- **Sleep/cold starts:** first hit after idleness takes ~30–60 s; sync buttons should retry (bounded retries built in). Schedule a cron ping (e.g. UptimeRobot free, GET `/health` every 15 min) to reduce sleeps — allowed within Render ToS for hobby projects.
- **Backups:** Neon free retains snapshots per plan terms; export CSV via `/export/csv` regularly as an extra backup. Recovery = restore snapshot (Neon dashboard) or re-import CSV.
- **Failure troubleshooting:** Render → Logs tab. Common: build errors (check pinned deps), `DATABASE_URL` missing driver prefix (`+psycopg2`), SSL errors (keep `?sslmode=require`), port binding (must use `$PORT`).

## Acceptance checklist (mark as you go)

- [ ] `/health` and `/docs` respond on public HTTPS URL
- [ ] Expense survives backend restart (Neon persistence)
- [ ] Frontend deployed at public streamlit.app URL
- [ ] Peer URLs/tokens exchanged and sync verified (after B & C deploy)
- [ ] Repeated sync creates no duplicates
- [ ] No secrets in the Git history (`git log -p | grep -i token` clean)

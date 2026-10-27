"""Application A - Smart Expense & Budget Manager (Streamlit frontend).

Owner: Sachien N (23MID0255).

Talks to the FastAPI backend over REST/JSON. The API base URL is configured
through the environment variable EXPENSE_API_URL (never hardcoded localhost
in production; the default is only for local development).

Run locally:  streamlit run app.py
"""
from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_BASE = os.environ.get("EXPENSE_API_URL", "http://localhost:8001").rstrip("/")
API_TOKEN = os.environ.get("EXPENSE_API_TOKEN", "")

st.set_page_config(page_title="Smart Expense & Budget Manager", page_icon="💰", layout="wide")
st.title("💰 Smart Expense & Budget Manager")
st.caption("Owner: Sachien N · Reg. No: 23MID0255 · CSI3007 Advanced Python Project")

CATEGORIES = ["Food", "Travel", "Bills", "Entertainment", "Shopping", "Subscriptions", "Other"]


def headers() -> dict:
    h = {"Accept": "application/json"}
    if API_TOKEN:
        h["Authorization"] = f"Bearer {API_TOKEN}"
    return h


def api(method: str, path: str, **kwargs):
    """Central API call helper with clear error handling."""
    try:
        resp = requests.request(method, f"{API_BASE}{path}", headers=headers(), timeout=15, **kwargs)
    except requests.RequestException as exc:
        st.error(f"Backend API unreachable at {API_BASE}: {exc}")
        return None
    if resp.status_code in (401, 403):
        st.error("Authentication failed - check EXPENSE_API_TOKEN.")
        return None
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        st.error(f"API error {resp.status_code}: {detail}")
        return None
    return resp


# ---------------- Sidebar: filters / month ----------------
st.sidebar.header("Controls")
month_default = dt.date.today().strftime("%Y-%m")
month = st.sidebar.text_input("Report month (YYYY-MM)", month_default)
page = st.sidebar.number_input("Page", min_value=1, value=1)
page_size = st.sidebar.select_slider("Rows per page", [10, 20, 50, 100], value=20)
search = st.sidebar.text_input("Search merchant/description")
f_category = st.sidebar.selectbox("Filter category", ["(all)"] + CATEGORIES)
f_source = st.sidebar.selectbox("Source", ["(all)", "manual", "app_b", "app_c", "csv"])

tab_list, tab_add, tab_budgets, tab_charts, tab_integrations = st.tabs(
    ["Expenses", "Add / Edit", "Budgets", "Charts", "Integrations"]
)

# ---------------- Expenses list ----------------
with tab_list:
    params = {"page": page, "page_size": page_size}
    if search:
        params["search"] = search
    if f_category != "(all)":
        params["category"] = f_category
    if f_source != "(all)":
        params["source"] = f_source
    data = api("GET", "/expenses", params=params)
    if data:
        payload = data.json()
        df = pd.DataFrame(payload["items"])
        if not df.empty:
            df["amount"] = pd.to_numeric(df["amount"])
            show = df[["id", "expense_date", "merchant", "amount", "currency",
                       "category", "payment_method", "source", "external_id",
                       "last_synced_at", "description"]]
            st.dataframe(show, use_container_width=True, hide_index=True)
            st.caption(f"Total records: {payload['total']} · showing page {payload['page']}")

            with st.expander("Delete an expense"):
                del_id = st.number_input("Expense ID", min_value=1, key="del_id")
                if st.button("Delete", key="btn_del"):
                    if api("DELETE", f"/expenses/{del_id}"):
                        st.success(f"Deleted expense {del_id}.")
                        st.rerun()
        else:
            st.info("No expenses yet - add one in the next tab.")

    col_a, col_b = st.columns(2)
    with col_a:
        try:
            csv_resp = requests.get(f"{API_BASE}/export/csv", headers=headers(), timeout=15)
            if csv_resp.status_code == 200:
                st.download_button("⬇️ Export all expenses (CSV)", csv_resp.content,
                                   file_name="expenses.csv", mime="text/csv")
        except requests.RequestException:
            st.info("CSV export unavailable (backend offline).")
    with col_b:
        up = st.file_uploader("⬆️ Import CSV (date,merchant,amount,category,...)", type="csv")
        if up and st.button("Import CSV"):
            r = api("POST", "/import/csv", files={"file": up.read()})
            if r:
                res = r.json()
                st.success(f"Imported {res['imported']} rows. Errors: {res['errors'] or 'none'}")
                st.rerun()

# ---------------- Add / edit ----------------
with tab_add:
    st.subheader("Add expense")
    with st.form("add_expense"):
        c1, c2 = st.columns(2)
        with c1:
            edate = st.date_input("Date", dt.date.today())
            merchant = st.text_input("Merchant *")
            amount = st.number_input("Amount *", min_value=0.0, step=0.01, format="%.2f")
        with c2:
            category = st.selectbox("Category", CATEGORIES)
            auto_cat = st.checkbox("Auto-categorize from merchant rules", value=True)
            payment = st.selectbox("Payment method", ["Card", "UPI", "Cash", "Net Banking", "Wallet"])
            desc = st.text_area("Description", height=68)
        if st.form_submit_button("Save expense"):
            if not merchant or amount <= 0:
                st.warning("Merchant and a positive amount are required.")
            else:
                cat = category
                if auto_cat:
                    r = api("GET", "/categorize", params={"merchant": merchant})
                    if r:
                        cat = r.json()["category"]
                body = {"expense_date": edate.isoformat(), "merchant": merchant,
                        "amount": str(Decimal(str(amount))), "category": cat,
                        "payment_method": payment, "description": desc or None}
                if api("POST", "/expenses", json=body):
                    st.success(f"Added ({cat}).")

    st.divider()
    st.subheader("Edit categorization rules (transparent & editable)")
    rules_data = api("GET", "/rules")
    if rules_data:
        rdf = pd.DataFrame(rules_data.json())
        st.dataframe(rdf, hide_index=True, use_container_width=True)
        with st.form("add_rule"):
            pattern = st.text_input("Merchant pattern (substring or glob, e.g. netflix or amc*)")
            rcat = st.selectbox("Category", CATEGORIES)
            if st.form_submit_button("Add / update rule") and pattern:
                if api("POST", "/rules", json={"pattern": pattern, "category": rcat}):
                    st.success("Rule saved.")
                    st.rerun()

# ---------------- Budgets ----------------
with tab_budgets:
    st.subheader(f"Monthly budgets - {month}")
    existing = api("GET", "/budgets", params={"month": month})
    if existing:
        bdf = pd.DataFrame(existing.json())
        if not bdf.empty:
            st.dataframe(bdf, hide_index=True, use_container_width=True)
    status = api("GET", "/budgets/status", params={"month": month})
    if status:
        sdf = pd.DataFrame(status.json()["statuses"])
        if not sdf.empty:
            sdf["pct_bar"] = sdf["utilization_percent"].clip(upper=150)
            st.bar_chart(sdf.set_index("category")["pct_bar"])
            st.dataframe(sdf.drop(columns=["pct_bar"]), hide_index=True, use_container_width=True)
            if (sdf["over_budget"]).any():
                st.warning("Some categories are over budget this month!")
    with st.form("add_budget"):
        bc1, bc2 = st.columns(2)
        with bc1:
            bmonth = st.text_input("Month (YYYY-MM)", month)
            bcat = st.selectbox("Category", CATEGORIES, key="bcat")
        with bc2:
            blimit = st.number_input("Limit amount", min_value=0.01, step=100.0, format="%.2f")
        if st.form_submit_button("Create budget"):
            if api("POST", "/budgets", json={"month": bmonth, "category": bcat,
                                             "limit_amount": str(Decimal(str(blimit)))}):
                st.success("Budget created.")
                st.rerun()

# ---------------- Charts ----------------
with tab_charts:
    summ = api("GET", "/summary", params={"month": month})
    if summ:
        s = summ.json()
        mcol1, mcol2, mcol3 = st.columns(3)
        mcol1.metric("Total spent", f"₹{float(s['total_spent']):,.2f}")
        ext_total = sum(s["external_sources"].values())
        mcol2.metric("From integrated apps", f"₹{ext_total:,.2f}")
        mcol3.metric("Categories used", len(s["by_category"]))
        if s["by_category"]:
            cdf = pd.DataFrame(s["by_category"])
            p1 = px.pie(cdf, names="category", values="total", title=f"Category breakdown - {month}")
            st.plotly_chart(p1, use_container_width=True)

    st.subheader("Spending trend (last 12 months)")
    trend_rows = []
    today = dt.date.today()
    for back in range(11, -1, -1):
        y = today.year + (today.month - 1 - back) // 12
        m = (today.month - 1 - back) % 12 + 1
        mm = f"{y:04d}-{m:02d}"
        r = api("GET", "/summary", params={"month": mm})
        if r:
            trend_rows.append({"month": mm, "total": float(r.json()["total_spent"])})
    if trend_rows:
        tdf = pd.DataFrame(trend_rows)
        st.plotly_chart(px.line(tdf, x="month", y="total", markers=True,
                                title="Monthly spending trend"), use_container_width=True)

# ---------------- Integrations ----------------
with tab_integrations:
    st.subheader("External applications")
    status = api("GET", "/integration/status")
    if status:
        js = status.json()
        for name, info in (("Subscription Tracker (App B)", js["subscription_api"]),
                           ("Electricity Manager (App C)", js["electricity_api"])):
            if info.get("reachable"):
                st.success(f"{name}: reachable ✅")
            elif not info.get("configured"):
                st.info(f"{name}: not configured (set SUBSCRIPTION_API_URL / ELECTRICITY_API_URL on the backend).")
            else:
                st.error(f"{name}: unreachable ❌ - {info.get('error')}")
        last = js.get("last_syncs", {})
        st.caption(f"Last successful syncs → App B: {last.get('app_b') or 'never'} · App C: {last.get('app_c') or 'never'}")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔄 Sync subscriptions now"):
            r = api("POST", "/sync/subscriptions")
            if r:
                res = r.json()
                st.write(res)
                st.success(f"Imported {res['records_imported']}, skipped duplicates {res['records_skipped']}.")
    with c2:
        if st.button("🔄 Sync electricity bills now"):
            r = api("POST", "/sync/electricity")
            if r:
                res = r.json()
                st.write(res)

    hist = api("GET", "/sync/history")
    if hist and hist.json():
        st.subheader("Sync history")
        st.dataframe(pd.DataFrame(hist.json()), hide_index=True, use_container_width=True)

    st.subheader("Imported external records")
    imp = api("GET", "/expenses", params={"page": 1, "page_size": 100})
    if imp:
        idf = pd.DataFrame([i for i in imp.json()["items"] if i["source"] != "manual"])
        if idf.empty:
            st.info("No imported records yet. Use the sync buttons above.")
        else:
            st.dataframe(idf[["id", "expense_date", "merchant", "amount", "category",
                              "source", "external_id", "last_synced_at"]],
                         hide_index=True, use_container_width=True)

# Note on privacy: when deployed publicly, dashboard data is visible to anyone
# with the URL. Keep secrets in environment variables only.

"""Application B - Subscription Renewal & Cost Tracker (Streamlit frontend).

Owner: Shravan N A (23MID0445).

Talks to the FastAPI backend over REST/JSON. The API base URL is configured
through the environment variable SUBSCRIPTION_API_URL (never hardcoded
localhost in production; the default is only for local development).

Run locally:  streamlit run app.py
"""
from __future__ import annotations

import datetime as dt
import os

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


def _cfg(key: str, default: str = "") -> str:
    """Env var first, then Streamlit Cloud secrets (st.secrets), then default."""
    value = os.environ.get(key)
    if value:
        return value
    try:
        sec = st.secrets  # works on Streamlit Community Cloud
        if key in sec:
            return str(sec[key])
    except Exception:
        pass  # no secrets.toml configured (local dev)
    return default


API_BASE = _cfg("SUBSCRIPTION_API_URL", "http://localhost:8002").rstrip("/")
API_TOKEN = _cfg("SUBSCRIPTION_API_TOKEN", "")

st.set_page_config(page_title="Subscription Renewal & Cost Tracker",
                   page_icon="🔁", layout="wide")
st.title("🔁 Subscription Renewal & Cost Tracker")
st.caption("Owner: Shravan N A · Reg. No: 23MID0445 · CSI3007 Advanced Python Project")

FREQUENCIES = ["monthly", "quarterly", "half-yearly", "annual"]
STATUSES = ["active", "paused", "cancelled", "expired"]
DEFAULT_CATEGORIES = ["Food", "Travel", "Bills", "Entertainment",
                      "Shopping", "Subscriptions", "Other"]


def headers() -> dict:
    h = {"Accept": "application/json"}
    if API_TOKEN:
        h["Authorization"] = f"Bearer {API_TOKEN}"
    return h


def api(method: str, path: str, **kwargs):
    """Central API call helper with clear error handling."""
    try:
        resp = requests.request(method, f"{API_BASE}{path}",
                                headers=headers(), timeout=15, **kwargs)
    except requests.RequestException as exc:
        st.error(f"Backend API unreachable at {API_BASE}: {exc}")
        return None
    if resp.status_code in (401, 403):
        st.error("Authentication failed - check SUBSCRIPTION_API_TOKEN.")
        return None
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        st.error(f"API error {resp.status_code}: {detail}")
        return None
    if resp.status_code == 204:
        return {}
    return resp.json()


# Categories come from Application A when reachable, else fall back locally.
status_info = api("GET", "/integration/status") or {}
CATEGORIES = status_info.get("categories_from_app_a") or DEFAULT_CATEGORIES
if status_info.get("expense_api", {}).get("reachable"):
    st.sidebar.success("Expense Manager (App A) categories loaded.")
else:
    st.sidebar.info("App A unreachable - using local category defaults. "
                    "This site still works normally.")

tab_list, tab_add, tab_renewals, tab_charts, tab_integration = st.tabs(
    ["Subscriptions", "Add / Edit", "Upcoming renewals", "Cost analysis",
     "Integration settings"]
)

# ------------------------------ Subscriptions ------------------------------
with tab_list:
    search = st.text_input("Search service or notes", "")
    col1, col2, col3 = st.columns(3)
    f_cat = col1.selectbox("Category", ["All"] + CATEGORIES)
    f_status = col2.selectbox("Status", ["All"] + STATUSES)
    f_freq = col3.selectbox("Frequency", ["All"] + FREQUENCIES)

    params = {"page_size": 200}
    if search:
        params["search"] = search
    if f_cat != "All":
        params["category"] = f_cat
    if f_status != "All":
        params["status"] = f_status
    if f_freq != "All":
        params["frequency"] = f_freq

    data = api("GET", "/subscriptions", params=params)
    if data:
        df = pd.DataFrame(data["items"])
        if not df.empty:
            df["monthly_equivalent"] = df.apply(
                lambda r: round(r["amount"] / {"monthly": 1, "quarterly": 3,
                                               "half-yearly": 6, "annual": 12}[r["billing_frequency"]], 2),
                axis=1,
            )
            show = df[["id", "service_name", "category", "plan", "amount",
                       "billing_frequency", "monthly_equivalent", "start_date",
                       "next_renewal", "status", "tags"]]
            st.dataframe(show.rename(columns={
                "service_name": "Service", "monthly_equivalent": "₹/month equiv.",
                "billing_frequency": "Billing", "next_renewal": "Next renewal",
            }), width="stretch")
            st.caption(f"{data['total']} subscriptions total.")

            with st.expander("Delete a subscription (local record only)"):
                del_id = st.number_input("Subscription id", min_value=1, step=1)
                if st.button("Delete"):
                    if api("DELETE", f"/subscriptions/{int(del_id)}") is not None:
                        st.success("Deleted from this tracker. Note: this does NOT "
                                   "cancel anything at the external provider.")
                        st.rerun()
        else:
            st.info("No subscriptions match the filters. Add one in the next tab.")

# ------------------------------ Add / Edit ------------------------------
with tab_add:
    st.subheader("Add a subscription")
    with st.form("add_sub", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Service name *", "Netflix")
        category = c1.selectbox("Category", CATEGORIES,
                               index=CATEGORIES.index("Entertainment")
                               if "Entertainment" in CATEGORIES else 0)
        plan = c2.text_input("Plan", "Premium")
        amount = c2.number_input("Amount per cycle *", min_value=0.01, value=499.0, step=10.0)
        currency = c2.text_input("Currency", "INR", max_chars=3)
        frequency = c3.select_slider("Billing frequency", options=FREQUENCIES, value="monthly")
        start = c3.date_input("Start date *", value=dt.date.today() - dt.timedelta(days=90))
        status_sel = c3.selectbox("Status", STATUSES, index=0)
        tags = st.text_input("Tags (comma separated)", "video")
        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Save subscription")
        if submitted:
            payload = {
                "service_name": name.strip(), "category": category,
                "plan": plan.strip() or None, "amount": str(amount),
                "currency": currency.upper(), "billing_frequency": frequency,
                "start_date": start.isoformat(), "status": status_sel,
                "tags": tags or None, "notes": notes or None,
            }
            if api("POST", "/subscriptions", json=payload) is not None:
                st.success("Subscription created.")
                st.rerun()

    st.divider()
    st.subheader("Update an existing subscription")
    upd_id = st.number_input("Subscription id to update", min_value=1, step=1, key="upd")
    new_status = st.selectbox("New status", ["(keep)", *STATUSES])
    new_amount = st.number_input("New amount per cycle (0 = keep)", min_value=0.0, value=0.0)
    if st.button("Apply update"):
        body: dict = {}
        if new_status != "(keep)":
            body["status"] = new_status
        if new_amount > 0:
            body["amount"] = str(new_amount)
        if not body:
            st.warning("Nothing to update.")
        elif api("PUT", f"/subscriptions/{int(upd_id)}", json=body) is not None:
            st.success("Updated.")
            st.rerun()

# ------------------------------ Renewals ------------------------------
with tab_renewals:
    days = st.segmented_control("Horizon", [7, 15, 30], default=30) or 30
    rows = api("GET", "/renewals", params={"days": days})
    if rows is not None:
        if rows:
            rdf = pd.DataFrame(rows)
            st.dataframe(rdf[["service_name", "amount", "currency",
                              "billing_frequency", "next_renewal",
                              "days_until_renewal"]].rename(columns={
                "service_name": "Service", "amount": "Charge",
                "billing_frequency": "Billing", "next_renewal": "Renews on",
                "days_until_renewal": "Days left"}), width="stretch",
                hide_index=True)
            timeline = px.bar(
                rdf.sort_values("next_renewal"),
                x="next_renewal", y="amount", color="service_name",
                title=f"Renewal timeline - next {days} days",
            )
            st.plotly_chart(timeline, width="stretch")
        else:
            st.success(f"No renewals due within {days} days. 🎉")

# ------------------------------ Cost analysis ------------------------------
with tab_charts:
    totals = api("GET", "/total")
    if totals:
        m1, m2, m3 = st.columns(3)
        m1.metric("Active subscriptions", totals["active_count"])
        m2.metric("Monthly equivalent cost", f"₹{totals['monthly_total']}")
        m3.metric("Annual cost", f"₹{totals['annual_total']}")
        if totals["by_category"]:
            cat_df = pd.DataFrame(
                [{"Category": k, "Monthly ₹": v} for k, v in totals["by_category"].items()]
            )
            pie = px.pie(cat_df, names="Category", values="Monthly ₹",
                         title="Monthly-equivalent spend by category")
            bar = px.bar(cat_df, x="Category", y="Monthly ₹",
                         title="Category comparison")
            p1, p2 = st.columns(2)
            p1.plotly_chart(pie, width="stretch")
            p2.plotly_chart(bar, width="stretch")

# ------------------------------ Integration ------------------------------
with tab_integration:
    st.subheader("Integration with Smart Expense Manager (Application A)")
    st.markdown(
        "- Sachien's Expense Manager **pulls** eligible recurring costs from "
        "this API's public `/subscriptions/export` feed.\n"
        "- Cancelled/expired subscriptions are never exported.\n"
        "- Repeated synchronization is idempotent: App A dedupes on record id, "
        "so no duplicate expenses are ever created.\n"
        "- ⚠️ Changing status here only updates **this tracker**; it never "
        "cancels a subscription at the external provider."
    )
    st.json(status_info)
    if st.button("🔄 Test export feed & connectivity now"):
        result = api("POST", "/sync/push-expenses")
        if result:
            if result["status"] == "success":
                st.success(f"Connectivity OK - {result['records_exported']} records "
                           "available for App A to pull.")
            else:
                st.warning(f"App A not reachable yet: {result.get('message')}")
        history = api("GET", "/sync/history")
        if history:
            st.dataframe(pd.DataFrame(history), width="stretch", hide_index=True)

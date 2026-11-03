import streamlit as st

st.set_page_config(page_title="MX Payments Ops Lab", page_icon="💸", layout="wide")

st.title("MX Payments Ops Lab")
st.caption("Synthetic data only. A product + engineering demo, not a production system.")

st.markdown(
    """
Two Mexican fintech problems, end to end:

- **SPEI BillPay Ops**: CLABE validation, bulk payment pre-flight, a SPEI simulator with
  returns and retries, reconciliation against a mock bank statement, and an ops dashboard.
- **Collections Workbench**: a seeded SME portfolio, delinquency analytics in SQL (DuckDB),
  explainable early-warning scores, a rules-based treatment engine, and a Spanish nudge
  drafter with compliance guardrails.

Use the sidebar to open a module.
"""
)

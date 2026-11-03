import plotly.express as px
import streamlit as st

from core.billpay_demo import sample_run
from core.billpay_metrics import compute_metrics
from core.recon import StatementNoise, generate_bank_statement, reconcile

st.set_page_config(page_title="BillPay dashboard", page_icon="📊", layout="wide")
st.title("BillPay dashboard")

run = st.session_state.get("billpay_run")
if run is None:
    st.caption(
        "No run in this session yet: showing the seeded sample file with default settings "
        "and account verification on."
    )
    run = sample_run().batch
else:
    st.caption("Showing the run from the Bulk payment run page.")

with st.sidebar:
    st.header("Mock bank statement")
    reformat = st.slider("Reformatted references", 0.0, 0.5, 0.06, 0.01)
    drift = st.slider("Small amount differences", 0.0, 0.5, 0.02, 0.01)
    missing = st.slider("Not yet posted", 0.0, 0.5, 0.03, 0.01)
    fees = st.number_input("Bank fee lines", 0, 20, 3)
    unknown = st.number_input("Unknown debits", 0, 20, 2)

noise = StatementNoise(reformat, drift, missing, True, int(fees), int(unknown))
statement = generate_bank_statement(run.payments, run.attempts, noise)
recon = reconcile(run.payments, statement)
m = compute_metrics(run, recon)
k = m.kpis


def pct(v):
    return "–" if v is None else f"{v:.1%}"


def hours(v):
    return "–" if v is None else f"{v:.1f} h"


c = st.columns(6)
c[0].metric("Payment success rate", pct(k["success_rate"]))
c[1].metric("First-attempt success", pct(k["first_attempt_success_rate"]))
c[2].metric("Median settlement", f"{k['median_settlement_s']:.1f} s")
c[3].metric("p90 settlement", f"{k['p90_settlement_s']:.1f} s")
c[4].metric("Return rate (per attempt)", pct(k["return_rate_per_attempt"]))
c[5].metric("Recon error rate", pct(k["recon_error_rate"]))

left, right = st.columns(2)
with left:
    st.subheader("Returns by reason")
    if m.returns_by_reason.empty:
        st.info("No returns in this run.")
    else:
        fig = px.bar(
            m.returns_by_reason,
            x="returns",
            y="reason_label",
            orientation="h",
            labels={"reason_label": "", "returns": "Returned attempts"},
        )
        fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), xaxis_dtick=1)
        st.plotly_chart(fig, width="stretch")
    st.caption("Reason labels are illustrative, not Banxico's official catalog.")
with right:
    st.subheader("Share settled within X seconds")
    settled = run.payments.dropna(subset=["settlement_s"])
    fig = px.ecdf(
        settled,
        x="settlement_s",
        log_x=True,
        labels={"settlement_s": "Seconds from first send to settlement (log scale)"},
    )
    fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, width="stretch")

st.subheader("Time to resolve failed transfers")
st.caption("Transfers with at least one return. Human resolution time is simulated.")
c = st.columns(2)
c[0].metric("Median", hours(k["median_hours_to_resolve_failed"]))
c[1].metric("p90", hours(k["p90_hours_to_resolve_failed"]))
st.dataframe(m.time_to_resolve, hide_index=True, width="stretch")

st.subheader("Reconciliation")
s = recon.summary
c = st.columns(5)
c[0].metric("Exact matches", s["exact"])
c[1].metric("Fuzzy matches", s["fuzzy"])
c[2].metric("Reversal pairs", s["reversal_pairs"])
c[3].metric("Unmatched payments", s["unmatched_payments"])
c[4].metric("Unmatched statement lines", s["unmatched_lines"])
a, b = st.columns(2)
with a:
    st.markdown("**Sent but not on the statement**")
    st.dataframe(
        recon.unmatched_payments[
            ["payment_id", "beneficiary", "reference", "amount_mxn", "settled_at"]
        ],
        hide_index=True,
        width="stretch",
    )
with b:
    st.markdown("**On the statement but not sent by us**")
    st.dataframe(recon.unmatched_lines, hide_index=True, width="stretch")
with st.expander("Fuzzy matches (review)"):
    st.dataframe(recon.matches[recon.matches["match_type"] == "fuzzy"], hide_index=True)
with st.expander("Mock bank statement"):
    st.dataframe(statement, hide_index=True, width="stretch")

with st.expander("SQL behind these metrics"):
    from core.db import load_sql

    for name in ("billpay_kpis", "billpay_returns_by_reason", "billpay_time_to_resolve"):
        st.code(load_sql(name), language="sql")

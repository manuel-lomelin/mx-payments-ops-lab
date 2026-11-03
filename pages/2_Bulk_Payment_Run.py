from pathlib import Path

import streamlit as st

from core.payments import (
    PreflightError,
    preflight,
    preflight_summary,
    read_payments_csv,
    to_instructions,
)
from core.retry import RetryPolicy
from core.spei_sim import SimConfig, run_batch

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_payments.csv"

st.set_page_config(page_title="Bulk payment run", page_icon="📤", layout="wide")
st.title("Bulk payment run (simulated SPEI)")
st.caption("Upload a supplier payment file, review the pre-flight report, then simulate sending.")

uploaded = st.file_uploader(
    "Payment CSV (beneficiary, clabe, amount_mxn, reference, concept)", type="csv"
)
st.download_button("Download sample file", SAMPLE.read_bytes(), "sample_payments.csv")

try:
    df = read_payments_csv(uploaded if uploaded else SAMPLE)
except PreflightError as exc:
    st.error(str(exc))
    st.stop()

st.subheader("1 · Pre-flight report")
st.caption("Using the uploaded file." if uploaded else "Using the seeded sample file.")
report = preflight(df)
summary = preflight_summary(report)
c = st.columns(5)
c[0].metric("Rows", summary["rows"])
c[1].metric("Ready", summary["ready"])
c[2].metric("Warnings", summary["warning"])
c[3].metric("Blocked", summary["blocked"])
c[4].metric("Sendable MXN", f"${summary['sendable_amount_mxn']:,.2f}")

only_issues = st.toggle("Show only rows with issues", value=True)
view = report[report["status"] != "ready"] if only_issues else report
st.dataframe(
    view[
        ["row", "status", "beneficiary", "clabe", "bank_name", "amount_mxn", "reference", "issues"]
    ],  # fmt: skip
    hide_index=True,
    width="stretch",
)

st.subheader("2 · Simulator settings")
defaults = SimConfig.from_config()
s = st.columns(4)
p_settled = s[0].slider("P(settled)", 0.0, 1.0, round(defaults.p_settled, 2), 0.01)
p_returned = s[1].slider("P(returned / devolución)", 0.0, 1.0, round(defaults.p_returned, 2), 0.01)
p_pending = s[2].slider("P(pending)", 0.0, 1.0, round(defaults.p_pending, 2), 0.01)
seed = s[3].number_input("Seed", value=7, step=1)
policy = RetryPolicy.from_config()
st.caption(
    f"Retry policy: max {policy.max_attempts} attempts, exponential backoff from "
    f"{policy.backoff.base_seconds:.0f}s. Retryable: {', '.join(sorted(policy.retryable_reasons))}."
    " Pending transfers are never re-sent."
)

if st.button(f"Send {summary['ready'] + summary['warning']} payments (simulated)", type="primary"):
    try:
        cfg = SimConfig.from_config(p_settled=p_settled, p_returned=p_returned, p_pending=p_pending)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    st.session_state["billpay_run"] = run_batch(
        to_instructions(report), cfg=cfg, policy=policy, seed=int(seed)
    )

run = st.session_state.get("billpay_run")
if run is not None:
    st.subheader("3 · Results")
    pays = run.payments
    r = st.columns(4)
    r[0].metric("Settled", int((pays["final_status"] == "settled").sum()))
    r[1].metric("Needs human", len(run.human_queue))
    r[2].metric("Payments with a return", int(pays["had_return"].sum()))
    r[3].metric("Total attempts", len(run.attempts))

    st.markdown("**Needs-human queue**")
    st.dataframe(
        run.human_queue[["payment_id", "beneficiary", "amount_mxn", "bank_name",
                         "last_reason_label", "attempts", "retries_exhausted", "next_action"]],
        hide_index=True,
        width="stretch",
    )  # fmt: skip
    with st.expander("All payments"):
        st.dataframe(pays, hide_index=True, width="stretch")
    with st.expander("Attempt log"):
        st.dataframe(run.attempts, hide_index=True, width="stretch")
    st.info("Open **BillPay Dashboard** for metrics and reconciliation of this run.")

import os

import streamlit as st

from core.account_verification import (
    CobreOwnershipLookup,
    VerificationCache,
    verification_summary,
)
from core.billpay_demo import SAMPLE_PAYMENTS, registry_for, run_pipeline
from core.payments import PreflightError, preflight, preflight_summary, read_payments_csv
from core.retry import RetryPolicy
from core.spei_sim import SimConfig

st.set_page_config(page_title="Bulk payment run", page_icon="📤", layout="wide")
st.title("Bulk payment run (simulated SPEI)")
st.caption(
    "Filter 1 checks every CLABE offline. Filter 2 proves new supplier accounts with a "
    "MXN 0.01 penny drop and an ownership lookup. Only verified payments are sent."
)

uploaded = st.file_uploader(
    "Payment CSV (beneficiary, clabe, amount_mxn, reference, concept, beneficiary_rfc)",
    type="csv",
)
st.download_button("Download sample file", SAMPLE_PAYMENTS.read_bytes(), "sample_payments.csv")

try:
    df = read_payments_csv(uploaded if uploaded else SAMPLE_PAYMENTS)
except PreflightError as exc:
    st.error(str(exc))
    st.stop()

st.subheader("1 · Filter 1: CLABE and file pre-flight")
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
    ],
    hide_index=True,
    width="stretch",
)

st.subheader("2 · Filter 2: account verification")
st.caption(
    "Penny drop: MXN 0.01 over SPEI. A return blocks the account; a settled cent's CEP "
    "must show the invoice RFC. Then an ownership lookup (Cobre-style, no money moved) "
    "cross-checks the owner. Verified accounts are reused on the next run."
)
verify = st.toggle("Verify accounts before paying", value=True)
cobre = CobreOwnershipLookup.from_env(os.environ)
lookup_choice = st.radio(
    "Ownership lookup provider",
    ["Simulated", "Cobre (live)"],
    horizontal=True,
    disabled=not verify,
    help="Cobre needs COBRE_USER_ID and COBRE_SECRET in the environment."
    if cobre is None
    else "Calls Cobre's Account Verification API with your credentials.",
)
if lookup_choice == "Cobre (live)" and cobre is None:
    st.warning("Set COBRE_USER_ID and COBRE_SECRET to use Cobre. Using the simulator.")
cache = st.session_state.setdefault("verification_cache", VerificationCache())
if st.button("Forget verified accounts"):
    st.session_state["verification_cache"] = cache = VerificationCache()

st.subheader("3 · Simulator settings")
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

if st.button(
    "Verify and send (simulated)" if verify else "Send (simulated)", type="primary", key="send"
):
    try:
        cfg = SimConfig.from_config(p_settled=p_settled, p_returned=p_returned, p_pending=p_pending)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    lookup = cobre if (lookup_choice == "Cobre (live)" and cobre is not None) else None
    st.session_state["billpay_demo"] = run_pipeline(
        report,
        registry_for(df, is_sample=uploaded is None),
        verify=verify,
        lookup=lookup,
        cache=cache,
        sim=cfg,
        policy=policy,
        seed=int(seed),
    )
    st.session_state["billpay_run"] = st.session_state["billpay_demo"].batch

demo = st.session_state.get("billpay_demo")
if demo is not None:
    if demo.verification is not None:
        st.subheader("Account verification results")
        v = verification_summary(demo.verification)
        c = st.columns(6)
        c[0].metric("Verified", v["verified"])
        c[1].metric("Penny returned", v["penny_returned"])
        c[2].metric("Wrong owner", v["wrong_owner"])
        c[3].metric("Held", v["held"])
        c[4].metric("Reused", v["reused"] + v["previously_blocked"])
        c[5].metric("Penny cost", f"${v['penny_cost_mxn']:,.2f}")
        not_ok = demo.verification[demo.verification["decision"] != "verified"]
        st.dataframe(
            not_ok[
                [
                    "payment_id",
                    "beneficiary",
                    "amount_mxn",
                    "decision",
                    "check",
                    "penny_reason",
                    "beneficiary_rfc",
                    "cep_rfc",
                    "lookup_outcome",
                    "next_action",
                ]
            ],
            hide_index=True,
            width="stretch",
        )
        with st.expander("All verification checks"):
            st.dataframe(demo.verification, hide_index=True, width="stretch")

    run = demo.batch
    st.subheader("Payment results")
    pays = run.payments
    r = st.columns(4)
    r[0].metric("Sent", len(pays))
    r[1].metric("Settled", int((pays["final_status"] == "settled").sum()))
    r[2].metric("Needs human", len(run.human_queue))
    r[3].metric("Payments with a return", int(pays["had_return"].sum()))
    st.markdown("**Needs-human queue**")
    st.dataframe(
        run.human_queue[
            [
                "payment_id",
                "beneficiary",
                "amount_mxn",
                "bank_name",
                "last_reason_label",
                "attempts",
                "retries_exhausted",
                "next_action",
            ]
        ],
        hide_index=True,
        width="stretch",
    )
    with st.expander("All payments"):
        st.dataframe(pays, hide_index=True, width="stretch")
    with st.expander("Attempt log"):
        st.dataframe(run.attempts, hide_index=True, width="stretch")
    st.info("Open **BillPay Dashboard** for metrics and reconciliation of this run.")

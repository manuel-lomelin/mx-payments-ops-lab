from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import plotly.express as px
import streamlit as st

from core.early_warning import backtest, compute_features, contributions, score
from core.nudges import (
    AccountContext,
    Draft,
    llm_available,
    llm_draft,
    prepare_and_check,
    seed_contact_log,
    template_draft,
)
from core.portfolio import generate_portfolio
from core.ptp import add_promise, summarize
from core.treatment import assign_all

st.set_page_config(page_title="Collections workbench", page_icon="🧰", layout="wide")
st.title("Collections workbench")
st.caption("Explainable risk score → rules-based treatment → Spanish draft → compliance check.")

TODAY = date(2026, 10, 1)  # the day after the synthetic portfolio's last statement


@st.cache_data
def load(n: int, seed: int):
    portfolio = generate_portfolio(n_accounts=n, seed=seed)
    scored = score(compute_features(portfolio))
    return portfolio, assign_all(scored, portfolio.accounts), backtest(portfolio)


n, seed = st.session_state.get("portfolio_params", (400, 2026))
portfolio, worklist, bt = load(n, seed)

if "contact_log" not in st.session_state:
    now = datetime.combine(TODAY, time(9, 0), ZoneInfo("America/Mexico_City"))
    st.session_state["contact_log"] = seed_contact_log(worklist, now)
if "promises" not in st.session_state:
    st.session_state["promises"] = portfolio.promises
log = st.session_state["contact_log"]

tab_list, tab_account, tab_log, tab_ptp = st.tabs(
    ["Worklist", "Account & nudge", "Blocked drafts", "Promises to pay"]
)

with tab_list:
    active = worklist[worklist["stage"] != "no_action"].sort_values(
        ["stage_order", "risk_score"], ascending=False
    )
    c = st.columns(4)
    c[0].metric("Accounts in treatment", len(active))
    c[1].metric("High risk", int((worklist["risk_band"] == "high").sum()))
    c[2].metric("Past due (MXN)", f"${active['past_due_amount'].sum():,.0f}")
    c[3].metric("Stages", active["stage"].nunique())
    st.dataframe(
        active[
            [
                "account_id",
                "company_name",
                "segment",
                "dpd_bucket",
                "current_dpd",
                "risk_score",
                "risk_band",
                "top_driver",
                "stage",
                "channel",
                "rule",
            ]
        ],
        hide_index=True,
        width="stretch",
    )
    st.markdown("**Does the score separate risk?** Score at month T-1, outcome at month T.")
    st.dataframe(
        bt,
        hide_index=True,
        column_config={
            "roll_rate": st.column_config.NumberColumn("rolled to a worse bucket", format="percent")
        },
    )
    st.caption("Backtest on synthetic data only: it shows the mechanics, not real-world lift.")

with tab_account:
    options = active["account_id"].tolist()
    acc_id = st.selectbox(
        "Account",
        options,
        format_func=lambda a: (
            f"{a} · " + str(worklist.loc[worklist["account_id"] == a, "company_name"].iloc[0])
        ),
    )
    row = worklist[worklist["account_id"] == acc_id].iloc[0]

    c = st.columns(5)
    c[0].metric("Bucket", row["dpd_bucket"])
    c[1].metric("Risk score", f"{row['risk_score']:.0f} ({row['risk_band']})")
    c[2].metric("Stage", row["stage"])
    c[3].metric("Channel", row["channel"])
    c[4].metric("State", row["state"])
    st.caption(f"Treatment rule: {row['rule']}")

    explained = contributions(row)
    fig = px.bar(
        explained,
        x="points",
        y="label",
        orientation="h",
        range_x=[0, 25],
        hover_data=["value", "max_points"],
        labels={"label": ""},
    )
    fig.update_layout(height=240, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, width="stretch")

    amount = float(row["past_due_amount"] or row["amount_due"])
    ctx = AccountContext(
        account_id=acc_id,
        first_name=row["contact_first_name"],
        company=row["company_name"],
        amount=amount,
        stage=row["stage"],
        channel=row["channel"],
        timezone=row["timezone"],
        pay_by=(TODAY + timedelta(days=7)).isoformat(),
        dpd=int(row["current_dpd"]),
    )

    st.subheader("Draft")
    left, right = st.columns([2, 1])
    with right:
        use_llm = st.toggle(
            "Draft with Claude",
            value=False,
            disabled=not llm_available(),
            help="Set ANTHROPIC_API_KEY to enable. Template is used otherwise.",
        )
        send_date = st.date_input("Send date", TODAY)
        send_time = st.time_input("Send time (debtor local)", time(10, 0), step=1800)
        send_at = datetime.combine(send_date, send_time, ZoneInfo(ctx.timezone))
    key = f"draft_{acc_id}_{use_llm}"
    if key not in st.session_state:
        st.session_state[key] = llm_draft(ctx) if use_llm else template_draft(ctx)
    base = st.session_state[key]
    with left:
        text = st.text_area("Message (edit it to see the guardrails react)", base.text, height=170)
        st.caption(f"Source: {base.source}" + (f" · {base.note}" if base.note else ""))
    draft = Draft(text, base.source if text == base.text else "manual")
    report = prepare_and_check(ctx, draft, send_at, log, int(row["max_contacts_per_week"]))

    st.markdown("**Compliance check**")
    for r in report.results:
        st.markdown(f"{'✅' if r.passed else '❌'} `{r.rule}` · {r.detail}")
    if st.button("Send (simulated)", type="primary"):
        if log.record(ctx, draft, report, send_at):
            st.success("Sent (simulated) and added to the contact history.")
        else:
            st.error("Blocked. The draft was logged in **Blocked drafts**.")

with tab_log:
    blocked = log.blocked_frame()
    st.metric("Blocked drafts this session", len(blocked))
    st.dataframe(blocked, hide_index=True, width="stretch")
    with st.expander("Sent this session"):
        sent = log.sent_frame()
        st.dataframe(sent[sent["source"] != "history"], hide_index=True, width="stretch")

with tab_ptp:
    promises = st.session_state["promises"]
    with st.form("new_ptp"):
        st.markdown("**Record a promise to pay**")
        c = st.columns(3)
        p_acc = c[0].selectbox("Account", options)
        p_amount = c[1].number_input("Amount (MXN)", min_value=1.0, value=5000.0, step=500.0)
        p_date = c[2].date_input("Promised date", TODAY + timedelta(days=7))
        if st.form_submit_button("Save promise"):
            dpd = int(worklist.loc[worklist["account_id"] == p_acc, "current_dpd"].iloc[0])
            try:
                st.session_state["promises"] = add_promise(
                    promises, p_acc, p_amount, p_date, TODAY, dpd
                )
                st.success("Promise recorded as pending.")
            except ValueError as exc:
                st.error(str(exc))
    s = summarize(st.session_state["promises"])
    st.dataframe(
        s["by_bucket"].fillna({"bucket_at_promise": "all"}),
        hide_index=True,
        width="stretch",
        column_config={"kept_rate": st.column_config.NumberColumn(format="percent")},
    )
    fig = px.line(s["by_month"], x="promise_month", y="kept_rate", markers=True)
    fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0), yaxis_tickformat=".0%")
    st.plotly_chart(fig, width="stretch")
    st.dataframe(st.session_state["promises"].tail(20), hide_index=True, width="stretch")

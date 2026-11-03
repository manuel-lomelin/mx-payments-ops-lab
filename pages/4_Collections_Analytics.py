import plotly.express as px
import streamlit as st

from core.collections_analytics import roll_rate_matrix, run_analytics
from core.db import load_sql
from core.portfolio import BUCKETS, generate_portfolio
from core.ptp import summarize

st.set_page_config(page_title="Collections analytics", page_icon="📉", layout="wide")
st.title("Collections analytics")
st.caption("Seeded synthetic SME portfolio · every number below comes from a .sql file in /sql.")

with st.sidebar:
    n_accounts = st.slider("Accounts", 100, 2000, 400, 100)
    seed = st.number_input("Seed", value=2026, step=1)


@st.cache_data
def load(n: int, seed: int):
    portfolio = generate_portfolio(n_accounts=n, seed=seed)
    return portfolio, run_analytics(portfolio)


portfolio, a = load(n_accounts, int(seed))
st.session_state["portfolio_params"] = (n_accounts, int(seed))


def show_sql(*names):
    with st.expander("SQL"):
        for name in names:
            st.code(load_sql(name), language="sql")


k = a["collections_kpis"].iloc[0]
c = st.columns(5)
c[0].metric("Accounts", int(k["accounts"]))
c[1].metric("Balance", f"${k['balance_mxn'] / 1e6:,.1f} M")
c[2].metric("Delinquency rate (DPD > 0)", f"{k['delinquency_rate']:.1%}")
c[3].metric("30+ DPD rate", f"{k['dpd_30_plus_rate']:.1%}")
c[4].metric("Balance 30+ share", f"{k['balance_30_plus_share']:.1%}")
show_sql("collections_kpis")

st.subheader("DPD buckets over time")
order = [*BUCKETS, "charged_off"]
fig = px.bar(
    a["dpd_buckets"],
    x="statement_month",
    y="share_accounts",
    color="bucket",
    category_orders={"bucket": order},
    labels={"share_accounts": "Share of accounts"},
)
fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(fig, width="stretch")
show_sql("dpd_buckets")

left, right = st.columns(2)
with left:
    st.subheader("Roll-rate matrix (month over month)")
    matrix = roll_rate_matrix(a["roll_rates"])
    fig = px.imshow(
        matrix,
        text_auto=".0%",
        color_continuous_scale="Blues",
        aspect="auto",
        labels={"x": "Bucket at t+1", "y": "Bucket at t", "color": "Roll rate"},
    )
    fig.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, width="stretch")
    show_sql("roll_rates")
with right:
    st.subheader("Cure rate")
    cure = a["cure_rate"].melt(
        "statement_month", ["cure_rate", "cure_rate_1_30", "cure_rate_31_plus"]
    )
    fig = px.line(
        cure,
        x="statement_month",
        y="value",
        color="variable",
        markers=True,
        labels={"value": "Share delinquent at t that is current at t+1"},
    )
    fig.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0), yaxis_tickformat=".0%")
    st.plotly_chart(fig, width="stretch")
    show_sql("cure_rate")

left, right = st.columns(2)
with left:
    st.subheader("Recovery rate (accounts that reached 90+)")
    rec = a["recovery_rate"].fillna({"segment": "all"})
    st.dataframe(
        rec,
        hide_index=True,
        width="stretch",
        column_config={"recovery_rate": st.column_config.NumberColumn(format="percent")},
    )
    show_sql("recovery_rate")
with right:
    st.subheader("Days to resolution")
    st.dataframe(a["days_to_resolution"], hide_index=True, width="stretch")
    st.caption("Open episodes at the end of the window are right-censored.")
    show_sql("delinquency_episodes", "days_to_resolution")

st.subheader("Vintage curves: ever 30+ DPD by months on book")
fig = px.line(
    a["vintage_curves"], x="months_on_book", y="ever_30_plus_rate", color="cohort", markers=True
)
fig.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0), yaxis_tickformat=".0%")
st.plotly_chart(fig, width="stretch")
st.caption("Cohorts are left-truncated: only months on book inside the 12-month window exist.")
show_sql("vintage_curves")

st.subheader("Promise-to-pay outcomes")
ptp = summarize(portfolio.promises)
left, right = st.columns(2)
with left:
    st.dataframe(
        ptp["by_bucket"].fillna({"bucket_at_promise": "all"}),
        hide_index=True,
        width="stretch",
        column_config={"kept_rate": st.column_config.NumberColumn(format="percent")},
    )
with right:
    fig = px.line(ptp["by_month"], x="promise_month", y="kept_rate", markers=True)
    fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0), yaxis_tickformat=".0%")
    st.plotly_chart(fig, width="stretch")
show_sql("ptp_outcomes", "ptp_by_month")

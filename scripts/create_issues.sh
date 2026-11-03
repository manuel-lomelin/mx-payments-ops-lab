#!/usr/bin/env bash
# Create the roadmap issues in the current GitHub repo. Run once after publishing.
set -euo pipefail

for label in billpay collections compliance analytics infra experiment docs enhancement; do
  gh label create "$label" --force >/dev/null
done

create() { gh issue create --title "$1" --label "$2" --body "$3"; }

create "Replace illustrative SPEI return reasons with Banxico's official catalog" "billpay,compliance" \
  "config/spei_returns.yaml uses illustrative labels on purpose. Map them to the official catalog and re-derive which reasons are retryable from real return data."
create "Supplier account verification before first payment (CLABE ownership)" "billpay,enhancement" \
  "NONEXISTENT_ACCOUNT and NAME_MISMATCH returns are preventable. Explore a penny-test or bank verification step during supplier onboarding."
create "Carry CFDI UUID through payments and reconciliation" "billpay,enhancement" \
  "Tie each payment to its invoice so reconciliation output can feed the payments complement (REP)."
create "Persist runs in a transactional store (Postgres) instead of session state" "infra" \
  "Keep DuckDB for analytics (ADR 0001); move payment state to a transactional database."
create "Maker-checker approval for bulk files above a threshold" "billpay,enhancement" \
  "Pre-flight already warns above max_amount_mxn. Add a second approver before sending."
create "Model cutoff times and SPEI operating hours in the simulator" "billpay,enhancement" \
  "Settlement latency currently ignores operating windows and participant cutoffs."
create "Opt-out and consent registry feeding the compliance checker" "collections,compliance" \
  "The checker cannot verify consent or opt-outs today (docs/compliance-notes.md)."
create "Score drift and fairness monitoring for the early-warning score" "collections,analytics" \
  "Track score distribution and band roll rates by month and segment."
create "Implement the nudge A/B test assignment and readout" "collections,experiment" \
  "Hash-based assignment, SRM check and readout per docs/experiments.md."
create "Interest and fees in the portfolio generator" "collections,analytics" \
  "Balances are frozen at 90+ and carry no interest, which flatters recovery rates."
create "Deploy to Streamlit Community Cloud and add the live link to the README" "docs" \
  "Main file: Home.py. Optional secret: ANTHROPIC_API_KEY."
create "Add README screenshots / GIF of each module" "docs" \
  "Record a short GIF of the bulk run → dashboard → workbench flow."

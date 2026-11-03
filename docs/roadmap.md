# Roadmap / backlog

These become GitHub Issues when the repo is published (`scripts/create_issues.sh`).

| Title | Labels |
|---|---|
| Replace illustrative SPEI return reasons with Banxico's official catalog | billpay, compliance |
| Real penny drop through the payment provider (payout + CEP retrieval by tracking key) | billpay, enhancement |
| Source the bank catalog from Banxico's participant list instead of Wikipedia | billpay, compliance |
| Carry CFDI UUID through payments and reconciliation | billpay, enhancement |
| Persist runs in a transactional store (Postgres) instead of session state | infra |
| Maker-checker approval for bulk files above a threshold | billpay, enhancement |
| Model cutoff times and SPEI operating hours in the simulator | billpay, enhancement |
| Opt-out and consent registry feeding the compliance checker | collections, compliance |
| Score drift and fairness monitoring for the early-warning score | collections, analytics |
| Implement the nudge A/B test assignment and readout (docs/experiments.md) | collections, experiment |
| Interest and fees in the portfolio generator | collections, analytics |
| Deploy to Streamlit Community Cloud and add the live link to the README | docs |
| Add README screenshots / GIF of each module | docs |

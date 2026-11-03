# ADR 0001 · DuckDB for storage and analytics

**Status:** accepted

## Context
The demo needs month-over-month roll rates, window functions, quantiles and cohort curves,
it has to run on Streamlit Community Cloud with no external services, and the analytics
should be readable by an analyst, not hidden in pandas chains.

## Decision
Use DuckDB in-process. Analytics live as plain `.sql` files in `/sql`, run against pandas
DataFrames registered as views (`core/db.py`). The UI shows the SQL next to each chart.
`make seed` also writes `data/lab.duckdb` for ad-hoc exploration.

## Consequences
- Zero infra; the same SQL runs in tests, the app and the DuckDB CLI.
- SQL is the contract with analysts: easy to review, easy to port to a warehouse later.
- State is per session and ephemeral. A real product needs a transactional store for
  payments (Postgres) and would keep DuckDB or a warehouse for analytics only.

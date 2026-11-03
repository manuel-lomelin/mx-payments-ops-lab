# ADR 0004 · Synthetic data and illustrative return reasons only

**Status:** accepted

## Context
This is a public portfolio project. Real payment files, debtor data or bank credentials
would be both a privacy problem and a misrepresentation.

## Decision
- All data is generated with fixed seeds: supplier payment files (`core/sample_data.py`) and
  the SME portfolio (`core/portfolio.py`). Names are obviously fake ("PyME Demo 0042",
  "Proveedor Demo 017", "Demo Finanzas").
- The only real-world names are public bank names in `data/banks.csv`.
- SPEI return reasons are internal, illustrative labels with no official numeric codes.

## Consequences
- Every number in the README comes from the synthetic demo and says nothing about any real
  portfolio or bank.
- Before real use: replace the return-reason catalog with Banxico's official one and
  re-validate the bank catalog.

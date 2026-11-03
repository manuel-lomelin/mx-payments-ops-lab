# One-pager · SPEI BillPay Ops

## Problem
Finance teams at Mexican SMEs pay suppliers in bulk over SPEI. A file with one wrong CLABE,
a duplicated row or a bank that times out turns into hours of manual work: chasing
returns (devoluciones), re-sending by hand, and reconciling the bank statement line by line.
The cost is not the failed transfer itself, it is the ops time, the late supplier and the
risk of paying twice.

## Users
- **Finance ops analyst**: uploads the payment file, works the exceptions queue.
- **Treasury / AP lead**: owns the cutoff, approves large transfers, signs off reconciliation.
- **CFO**: wants suppliers paid on time and a clean month-end close.

## Hypotheses
1. Most returns are preventable before sending: CLABE check digit, bank code, duplicates and
   field limits catch a large share of bad rows at pre-flight.
2. Infrastructure failures (receiving bank unavailable, timeout) recover on automatic retry;
   account problems never do and should go straight to a human with a suggested next step.
3. Exact reference + amount matching handles most of reconciliation; a small fuzzy layer
   handles reformatted references, and what remains is the real exception list.
4. Proving a new supplier account with a MXN 0.01 penny drop (and an ownership lookup)
   before its first payment removes most account-problem returns and stops payments to a
   CLABE that is not the supplier's, for one cent per account.

## Metrics
- **North star:** share of payments settled with zero human touch (pre-flight → settled →
  auto-reconciled).
- **Supporting:** payment success rate, first-attempt success, median and p90 settlement
  time, return rate by reason, reconciliation error rate, time to resolve failed transfers.
- **Guardrails:** duplicate payments (target 0), payments re-sent while pending (target 0),
  share of blocked rows that were actually valid (false-positive pre-flight blocks),
  payments to an unverified account (target 0), first payments delayed by verification.

## First 30 / 60 / 90 days
- **30:** instrument the funnel (uploaded → blocked → sent → settled → reconciled). Baseline
  the return rate by reason and bank, and measure how long analysts spend per exception.
- **60:** ship pre-flight + retry policy to a pilot cohort; measure first-attempt success and
  the needs-human queue size vs. baseline; tune which reasons are retryable from real data.
- **90:** auto-reconciliation live; target a drop in month-end close time and in manual
  matches. Turn on account verification (penny drop + ownership lookup) for new suppliers
  and compare account-problem returns and wrong-account incidents against the baseline.

## Risks
- **SAT / CFDI:** supplier payments should tie back to CFDI invoices; payments on PPD
  invoices require a payment receipt (CFDI with the payments complement). Reconciliation
  should carry the invoice UUID, which this demo does not model.
- **CNBV / Banxico:** moving client funds over SPEI requires operating through a regulated
  participant (bank or authorized institution). The product sits on top of one; it is not one.
- **PLD / AML:** supplier onboarding needs KYC/KYB, beneficiary screening and unusual-operation
  monitoring. Bulk files are a known vector for paying unvetted beneficiaries.
- **Operational:** a naive retry on a pending transfer can pay a supplier twice. The policy
  here never re-sends while pending (see ADR 0002).

All of the above is high level and needs review with legal/compliance counsel.

## What I deliberately did NOT build
- A real SPEI connection, CEP (comprobante electrónico de pago) retrieval or Banxico codes.
- Approval workflows, maker-checker, roles and permissions.
- CFDI matching and supplier master-data management.
- Multi-currency, scheduled payments, cutoff-time handling.

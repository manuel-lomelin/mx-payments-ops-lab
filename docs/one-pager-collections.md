# One-pager · Collections Workbench

## Problem
SME lenders and spend-management platforms extend credit lines and collect in a very manual
way: one-size-fits-all reminders, agents calling from spreadsheets, and messages that
sometimes cross the line on tone or contact hours. Delinquency rolls forward because the
right account does not get the right treatment early enough, and compliance risk grows
with every unsupervised message.

## Users
- **Collections agent**: works a prioritized list, needs a ready-to-send, compliant message.
- **Collections manager**: owns strategy (who gets what, when), reviews roll rates and cures.
- **CFO / risk**: watches loss rates, recovery and portfolio health by vintage.

## Hypotheses
1. A small set of behavioural signals (utilization spike, partial or missed payments, broken
   promises) ranks next-month roll risk well enough to prioritize, and is explainable to
   agents and auditors.
2. Matching treatment intensity to bucket and risk (nudge before call before plan before
   agency) cures more early-bucket accounts at lower cost than uniform treatment.
3. LLM-personalized messages can improve response, but only behind deterministic guardrails;
   rules decide *whether and when* to contact, the LLM only helps with *wording*.

## Metrics
- **North star:** 30-day cure rate of accounts entering 1-30 DPD.
- **Supporting:** roll-rate matrix (especially 1-30 → 31-60), cure rate by bucket, recovery
  rate on 90+, days to resolution, promise-to-pay kept rate, vintage ever-30+ curves.
- **Guardrails:** compliance blocks per 1,000 drafts, complaints (e.g. via CONDUSEF channels),
  opt-outs, contacts outside the allowed window (target 0), frequency-cap breaches (target 0).

## First 30 / 60 / 90 days
- **30:** baseline roll rates, cure rates and PTP kept rate from the real portfolio. Backtest
  the early-warning score (the demo backtest shows the mechanics on synthetic data only).
- **60:** launch the treatment rules to one segment; ship template nudges with the compliance
  checker in front of every send; log every blocked draft and review them weekly.
- **90:** run the nudge A/B test in `docs/experiments.md`; decide whether LLM drafting earns
  its cost and risk based on cure rate and guardrail metrics, not on message quality alone.

## Risks
- **Consumer-protection / CONDUSEF:** collection contact hours, tone, sender identification
  and third-party contact are regulated for collection agencies. See
  `docs/compliance-notes.md`; verify the current text with counsel.
- **CNBV:** lenders are supervised entities; strategy changes need documented governance.
- **PLD / AML:** unusual repayment patterns (third-party payers, structuring) need monitoring.
- **SAT / CFDI:** payment plans and write-offs have invoicing and tax implications.
- **Model risk:** even a points-based score needs monitoring for drift and disparate impact.

## What I deliberately did NOT build
- Real WhatsApp / email / dialer integrations or opt-in management.
- A trained ML model (explainable points beat a black box for a first version).
- Legal workflows, agency marketplace, settlement/discount optimization.
- Credit bureau reporting.

# Experiment design · Collections nudge A/B test

## Question
Does a personalized, LLM-drafted WhatsApp nudge (behind the same guardrails) cure more
early-delinquent accounts than the deterministic template?

## Hypothesis
Accounts entering 1-30 DPD that receive the personalized nudge cure (are current at the next
statement) more often than those receiving the template, with no increase in complaints.

## Design
- **Unit of randomization:** the account (not the message), so an account always sees one
  arm and contact-frequency effects do not leak across arms.
- **Population:** accounts entering 1-30 DPD whose treatment stage is `nudge`; excludes
  accounts with an open payment plan or a dispute.
- **Arms (50/50):** A = template (control), B = LLM draft. Same channel, same send-time rule,
  same frequency caps, same compliance checker. Drafts blocked by the checker fall back to
  the template and are counted (intent-to-treat).
- **Assignment:** deterministic hash of `account_id` + experiment salt; log assignment
  before the first send.

## Metrics
- **Primary:** 30-day cure rate (DPD = 0 at the next statement).
- **Secondary:** PTP made and kept rates, days to resolution, amount collected in 30 days.
- **Guardrails:** complaints per 1,000 accounts, opt-outs, compliance block rate in arm B,
  contacts outside the window (must be 0 in both arms).

## Sample size and MDE
Baseline: the demo shows ~80% cure for 1-30 (synthetic; replace with the real baseline).
For an absolute MDE of +3 pp (80% → 83%), alpha = 0.05 two-sided, power = 0.80:

n per arm = (1.96 + 0.84)² × (0.80·0.20 + 0.83·0.17) / 0.03² ≈ **2,623 accounts**.

## Duration
Fixed horizon: time to enroll 2 × 2,623 accounts plus a 30-day outcome window. At, say,
1,000 new 1-30 entries per week that is ~5-6 weeks of enrollment + 30 days. Run at least two
full billing cycles to average out day-of-month effects.

## Stop rules
- **Stop immediately** on any confirmed compliance incident attributable to arm B, or if
  the guardrail complaint rate in B is significantly above A.
- **Sample-ratio mismatch** check weekly (chi-square on assignment counts); pause if p < 0.001.
- No early stopping for success on peeks. If interim looks are needed, pre-register an
  alpha-spending plan (e.g. O'Brien-Fleming).

## Decision rule
Ship B if the primary metric improves with the CI excluding 0 and no guardrail degrades.
If the effect is positive but below the MDE, weigh LLM cost and review overhead before
shipping.

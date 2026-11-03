# ADR 0003 · Rules + LLM instead of LLM-only for collections

**Status:** accepted

## Context
LLMs write friendlier, more personal messages. They also occasionally produce text that is
non-compliant, wrong about the amount, or missing the payment instructions, and they cannot
be the system of record for *when* and *how often* a debtor is contacted.

## Decision
- **Rules decide**: the early-warning score is a points table; treatment stages come from
  YAML rules; contact window and frequency caps are deterministic checks.
- **The LLM only drafts wording**, with the facts (amount, CLABE, reference, sender) passed
  in explicitly.
- **Every draft**, template or LLM or hand-edited, runs through the same compliance checker.
  A draft that fails any rule cannot be sent and is logged.
- The app works fully without an API key: templates are the default and the fallback on
  any error or refusal.

## Consequences
- Auditable: every decision traces to a config line or a rule result.
- The LLM can be switched off with no loss of function, so its value can be A/B tested
  (`docs/experiments.md`) instead of assumed.
- Pattern-based checks have false negatives; logging blocked drafts and human review stay
  necessary.

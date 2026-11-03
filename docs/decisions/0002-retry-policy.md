# ADR 0002 · Retry and fallback policy for SPEI transfers

**Status:** accepted

## Context
A returned transfer is either an infrastructure problem (receiving participant unavailable,
timeout) or an account problem (nonexistent, blocked, cancelled, wrong type, name mismatch).
Retrying account problems wastes attempts and annoys the receiving bank; not retrying
infrastructure problems creates manual work. Re-sending a transfer that is still *pending*
can pay the supplier twice.

## Decision
- Retry only reasons marked `retryable` in `config/spei_returns.yaml`
  (RECEIVER_UNAVAILABLE, TIMEOUT), up to `max_attempts: 3` including the first send.
- Exponential backoff: 60s, 120s, 240s... capped at 900s, with ±10% jitter.
- **Never re-send while pending.** Wait for a final status; a pending transfer that later
  returns with TIMEOUT is then eligible for retry.
- Everything else goes to a needs-human queue with a suggested next action per reason.

## Consequences
- No double payments by construction (asserted in tests: retries start only after the
  previous attempt resolved).
- Reason labels are illustrative, not Banxico's official catalog; the retryable set must be
  re-derived from real return data with the bank.

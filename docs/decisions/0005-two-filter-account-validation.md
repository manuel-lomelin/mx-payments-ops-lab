# ADR 0005 · Two filters before paying a new supplier account

**Status:** accepted

## Context
A CLABE can be perfectly valid (18 digits, correct check digit, known bank) and still be
useless or dangerous: the account may not exist, may be blocked or cancelled, or may belong
to someone other than the supplier. The last case is the "we changed banks, pay this new
CLABE" fraud pattern. Finding out from a returned or misdirected real payment is the most
expensive way to learn it.

## Decision
**Filter 1 (offline, free, every row):** CLABE structure, 3-7-1 check digit and bank code
against the catalog from the Spanish Wikipedia CLABE article, plus the other pre-flight
rules. Anything that fails never reaches filter 2.

**Filter 2 (once per new CLABE + RFC pair):**
1. **Penny drop.** Send MXN 0.01 over SPEI. A return blocks the account with its reason. A
   settled cent comes with a CEP; its beneficiary RFC must equal the RFC on the supplier's
   invoice, otherwise the account is blocked as a wrong owner.
2. **Ownership lookup.** Ask the provider whether the CLABE belongs to that RFC, without
   moving money (Cobre Account Verification, model `mex_acc_ownership_1`). It is a
   cross-check: if it says `unmatched` while the penny matched, the payment is held for
   review; if it is inconclusive (`unresolved`, `failed`, provider down), the penny decides.

Verified pairs are reused for 180 days; blocked pairs stay blocked until the supplier
record changes. Only verified payments are sent. In the simulator, verified accounts can no
longer be returned as nonexistent, name mismatch or account-type mismatch.

## Why the penny drop is primary
It is the only check that proves money actually lands, and the CEP is Banxico's own record
of who received it. The lookup is cheap and fast to add but answers a narrower question,
and Cobre's docs describe it as asynchronous with business-hour response windows and a
12-hour wait before retrying a check.

## Consequences
- Each new supplier account costs one cent and a few seconds to minutes of latency before
  its first payment. Paying on the same day still works; the very first payment just waits
  for the cent.
- A real penny drop needs a funded SPEI account and CEP retrieval by tracking key; here it
  runs on the simulator. The Cobre lookup client is written from public docs and is not
  exercised against the live API in this repo.
- Wikipedia's bank table lags real participant changes. Before production, the catalog
  should come from Banxico's participant list (or the payment provider's catalog).

# Compliance notes (read before reusing any of this)

These notes explain why the guardrails in `config/compliance.yaml` exist. They are a
product manager's high-level reading, not legal advice. **Verify every point against the
current official text and with counsel before real use.**

## Collection contact rules
CONDUSEF publishes general provisions for financial entities and the collection agencies
(despachos de cobranza) acting for them, and runs a public registry of those agencies
(REDECO). As I read them, they include:

- **Contact hours:** contact the debtor only between **07:00 and 22:00, in the debtor's local
  time**. The checker converts the send time to the account's IANA timezone (Mexico has
  several) before comparing. Default: `07:00-22:00`, configurable.
- **Identification:** the person or agency contacting must identify themselves and the
  entity they collect for. The checker requires the sender name in every message.
- **No threats, intimidation or offensive language**, and no pretending to be a legal
  authority. The checker blocks a Spanish pattern list (threats, insults, fake
  court/prosecutor language), accent- and case-insensitive.
- **No pressure through third parties** (family, neighbours, employer, the debtor's clients).
- **Clear information:** state what is owed and how to pay. The checker requires the exact
  amount and a payment option (CLABE, reference or link).

## Frequency caps
The daily and weekly caps (`1/day`, `3/week`, tightened by each treatment stage) are an
**internal policy choice for this demo**, not a quote from any regulation.

## What the checker cannot do
- It is pattern-based: a determined writer can phrase a threat it does not catch. That is why
  LLM output is never trusted, rules decide when to contact, and blocked drafts are logged
  for human review.
- It does not verify consent, opt-outs, or that a phone number belongs to the debtor.

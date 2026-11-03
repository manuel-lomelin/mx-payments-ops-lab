<div align="center">

# 💸 mx-payments-ops-lab

### What happens *after* a Mexican SME hits "pay" or "collect", and how to make it boring.

A hands-on lab for two problems every LatAm spend-management fintech eventually owns:<br>
**getting supplier payments over SPEI to land**, and **collecting from B2B customers without crossing the line**.

[![CI](https://github.com/manuel-lomelin/mx-payments-ops-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/manuel-lomelin/mx-payments-ops-lab/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B?logo=streamlit&logoColor=white)
![DuckDB](https://img.shields.io/badge/analytics-DuckDB-FFF000?logo=duckdb&logoColor=black)
![Coverage](https://img.shields.io/badge/core%20coverage-99%25-2ea44f)
![Data](https://img.shields.io/badge/data-100%25%20synthetic-8250df)
![License](https://img.shields.io/badge/license-MIT-blue)

[**What it does**](#-what-the-lab-does) · [**Why it matters**](#-who-it-helps-and-how) · [**Why it's built this way**](#-why-its-built-this-way) · [**Run it**](#-run-it-in-two-commands) · [**Product docs**](#-product-thinking-not-just-code)

<img src="docs/img/billpay-dashboard.png" alt="BillPay dashboard" width="90%">

</div>

---

## 🧭 The problem in one minute

**Paying suppliers.** A finance analyst uploads a file with 120 supplier payments. One CLABE
has a typo, two rows are duplicates, a receiving bank times out at 10:02, and the statement
prints references differently from what was sent. None of that is hard. All of it is manual,
and the worst outcome isn't a failed payment, it's **paying the same supplier twice**.

**Collecting from customers.** A lender has 400 SME credit lines. Some customers are a few
days late and will pay with a friendly WhatsApp; others are sliding toward 90+ days. Agents
work from a spreadsheet, every account gets the same message, and sooner or later someone
sends a text at 11 pm that hints at "legal consequences". That's a **CONDUSEF complaint
waiting to happen**.

This lab turns both workflows into something you can click through, measure, and argue about.

---

## 🔬 What the lab does

### Module 1 · SPEI BillPay Ops

```mermaid
flowchart LR
    A[📄 Payment CSV] --> B{Pre-flight}
    B -- blocked --> X[❌ Fix before sending<br/>bad CLABE · duplicate · bad amount]
    B -- ready --> C[🏦 SPEI simulator]
    C -- settled --> R[🔁 Reconciliation]
    C -- returned, retryable --> D[⏳ Backoff & retry]
    D --> C
    C -- returned, account problem --> H[🙋 Needs-human queue<br/>with next action]
    C -- pending --> W[⏸ Wait for final status<br/>never re-send]
    W --> C
    R --> M[📊 Dashboard]
    H --> M
```

| Step | What you see | Why it matters |
|---|---|---|
| **CLABE validator** | 18 digits split into bank / plaza / account / check digit, verified with Banxico's 3-7-1 weights | The cheapest failure to prevent is the one caught before sending |
| **Pre-flight report** | Every row marked *ready*, *warning* or *blocked*, with the reason | The analyst fixes 9 rows instead of chasing 9 returns |
| **SPEI simulator** | Settled / returned (devolución) / pending, realistic latency, tunable odds | Lets you stress-test ops flows without a bank |
| **Retry policy** | Infra failures retried with backoff; account failures routed to a human with a suggested fix | Fewer manual re-sends, **zero double payments by design** |
| **Reconciliation** | Exact match → fuzzy match → unmatched *both ways* (sent-not-posted and posted-not-sent) | Month-end close becomes an exception list, not a spreadsheet hunt |
| **Dashboard** | Success rate, median/p90 settlement, returns by reason, recon error rate, time to resolve | Ops gets the same numbers the CFO asks for |

### Module 2 · Collections Workbench

```mermaid
flowchart LR
    P[🏢 SME portfolio<br/>12 months of history] --> S[🧮 Early-warning score<br/>explainable points]
    S --> T[🗺 Treatment rules<br/>reminder → nudge → call → plan → agency]
    T --> N[✍️ Spanish draft<br/>template or Claude]
    N --> G{🛡 Compliance check}
    G -- all 6 rules pass --> OK[✅ Send]
    G -- any rule fails --> BL[🚫 Blocked & logged]
    OK --> PTP[🤝 Promise-to-pay tracker]
    PTP --> A[📈 Roll rates · cures · recovery · vintages]
    P --> A
```

| Step | What you see | Why it matters |
|---|---|---|
| **Delinquency analytics** | DPD buckets, roll-rate matrix, cure and recovery rates, days to resolution, vintage curves, all in plain SQL shown next to each chart | The metrics a collections strategy is judged by, readable by any analyst |
| **Early-warning score** | 0-100 points from 5 behaviours (utilization spike, partial/missed payments, broken promises, DPD), with a bar chart of *why* | Agents trust what they can explain; auditors too |
| **Treatment engine** | First-match rules by bucket, segment and risk, editable in YAML | Strategy changes are a config diff, not a deploy |
| **Nudge drafter** | A Spanish WhatsApp/email/call script per account and stage | Faster, more personal outreach |
| **Compliance guardrails** | ✅/❌ per rule: contact window in the debtor's timezone, no threats or abuse, sender named, exact amount, payment option, frequency caps | **No message leaves without passing**, whoever or whatever wrote it |
| **Promise-to-pay tracker** | Record promises, see kept vs. broken by bucket and month | Tells you which promises are worth believing |

<div align="center">
<img src="docs/img/compliance-check.png" alt="Compliance guardrails catching a threat" width="85%">
<br><sub>Type a threat into any draft and watch it get blocked: <code>no_threats_or_abuse · threat: 'carcel'</code></sub>
</div>

---

## 🎯 Who it helps and how

| Persona | Pain today | What the lab gives them |
|---|---|---|
| 🧾 **Finance ops analyst** | Chasing returns and re-sending by hand | Pre-flight before sending, auto-retry for infra failures, a short queue with the next step written out |
| 🏦 **Treasury / AP lead** | Fear of double payments, slow month-end close | A retry policy that never re-sends pending transfers, reconciliation that surfaces only real exceptions |
| 📞 **Collections agent** | Same script for everyone, unsure what's allowed | A prioritized worklist, the reason each account is risky, a compliant draft ready to send |
| 📋 **Collections manager** | Strategy lives in someone's head | Roll rates and cures to steer by, treatment rules in one YAML file |
| 📊 **CFO** | Can't see where cash gets stuck | Success, settlement time, recovery and vintage curves, with the SQL behind every number |
| ⚖️ **Compliance** | Hopes agents behave | Deterministic rules, a block log, and an LLM that can't bypass either |

### What the seeded demo shows

> These numbers come from synthetic data with fixed seeds. They show that the mechanics work,
> not how any real bank or portfolio performs.

| BillPay run (120-row file) | | Collections portfolio (400 SMEs) | |
|---|---|---|---|
| Rows blocked at pre-flight | **9** | Accounts with DPD > 0 | **23%** |
| Payments settled | **94.6%** | 1-30 DPD that cure next month | **80%** |
| Median / p90 settlement | **3.7 s / 8.8 s** | Recovery on 90+ exposure | **33%** |
| Reconciliation error rate | **5.2%** | Next-month roll rate, low → high risk band | **15% → 36% → 83%** |
| Median time to resolve a return | **4.1 h** (simulated) | Promises to pay kept | **79%** |

---

## 🏗 Why it's built this way

Every choice below is a product decision first and a technical one second. The long form is
in the [ADRs](docs/decisions/).

<table>
<tr>
<td width="50%" valign="top">

**🧱 Rules decide, the LLM only writes**<br>
Whether and when to contact someone is a deterministic rule. Claude helps with *wording*, and
its output goes through the same six checks as a template. With no API key the app still
does everything. → [ADR 0003](docs/decisions/0003-rules-plus-llm.md)

</td>
<td width="50%" valign="top">

**🔁 Never re-send a pending transfer**<br>
Retry only what's retryable (receiving bank down, timeout) and wait on anything still in
flight. The tests assert that no retry starts before the previous attempt resolved.
→ [ADR 0002](docs/decisions/0002-retry-policy.md)

</td>
</tr>
<tr>
<td valign="top">

**🧮 Explainable over clever**<br>
The risk score is a points table, not a model. Every point traces to one behaviour, and a
T-1 → T backtest checks that higher bands really roll more.

</td>
<td valign="top">

**🦆 SQL as the contract (DuckDB)**<br>
Roll rates, cures and KPIs are plain `.sql` files that run in-process, in tests, in the app
and in the DuckDB CLI. No servers, and an analyst can review every number.
→ [ADR 0001](docs/decisions/0001-duckdb-for-storage-and-analytics.md)

</td>
</tr>
<tr>
<td valign="top">

**⚙️ Business rules in YAML**<br>
Return reasons, retry limits, score weights, treatment stages, compliance patterns and
message templates all live in [`config/`](config/). Ops can tune them without touching code.

</td>
<td valign="top">

**🧪 Honest by construction**<br>
100% synthetic, seeded data ([ADR 0004](docs/decisions/0004-synthetic-data-and-illustrative-codes.md)).
SPEI return reasons are labelled illustrative. Every number in this README comes from the
seeded demo and can be reproduced with the default seeds.

</td>
</tr>
</table>

### Architecture

```mermaid
flowchart LR
    subgraph UI["🖥 Streamlit · Home.py + pages/"]
        direction TB
        P1[CLABE validator]
        P2[Bulk payment run]
        P3[BillPay dashboard]
        P4[Collections analytics]
        P5[Collections workbench]
    end

    subgraph Core["🧠 core/ · pure Python, 99% tested"]
        direction TB
        CL[clabe] --> PF[payments] --> SIM[spei_sim] --> RT[retry]
        SIM --> RC[recon]
        PG[portfolio] --> EW[early_warning] --> TR[treatment] --> NU[nudges] --> CP[compliance]
        PG --> PTP[ptp]
    end

    CFG[[⚙️ config/*.yaml]] -.-> Core
    SQL[(🦆 DuckDB · sql/*.sql)]
    LLM{{🤖 Claude API · optional}} -.-> NU

    UI --> Core
    Core --> SQL
```

`core/` never imports Streamlit, so the domain logic is tested on its own. The UI is a
thin layer over it.

---

## 🚀 Run it in two commands

```bash
git clone https://github.com/manuel-lomelin/mx-payments-ops-lab.git && cd mx-payments-ops-lab
make setup && make run
```

Then open http://localhost:8501. Requires Python 3.11+.

**Suggested 3-minute tour**
1. **Bulk Payment Run**: review the pre-flight report, then hit *Send*. Push *P(returned)* up and send again.
2. **BillPay Dashboard**: drag the bank-statement noise sliders and watch reconciliation react.
3. **Collections Analytics**: read the roll-rate matrix, then open any *SQL* expander.
4. **Collections Workbench**: pick an account, see why it's risky, then add *"irá a la cárcel"* to the draft. It gets blocked.

<details>
<summary><b>More commands and the optional LLM</b></summary>

| Command | Does |
|---|---|
| `make test` | Run the test suite |
| `make cov` | Tests with coverage on `/core` (CI gate: 80%) |
| `make lint` | Ruff lint + format check |
| `make seed` | Rewrite `data/sample_payments.csv` and build `data/lab.duckdb` for ad-hoc SQL |

Try the SQL directly: `duckdb data/lab.duckdb < sql/roll_rates.sql`

**Optional Claude drafting:** copy `.env.example` to `.env` (or export the variables) and set
`ANTHROPIC_API_KEY`. Drafts then use `claude-opus-5-5` (override with `ANTHROPIC_MODEL`) with
the API's server-side refusal fallback enabled. Without a key, deterministic Spanish
templates are used, and LLM drafts go through the same compliance checks.

</details>

---

## 🧠 Product thinking, not just code

| Doc | What's in it |
|---|---|
| [One-pager · BillPay](docs/one-pager-billpay.md) | Problem, users, hypotheses, north-star and guardrail metrics, 30/60/90 days, SAT/CNBV/PLD risks, what I didn't build |
| [One-pager · Collections](docs/one-pager-collections.md) | Same structure for the collections workbench |
| [Experiment design](docs/experiments.md) | A/B test for the nudge: unit, primary metric, MDE with the sample-size math, stop rules |
| [Compliance notes](docs/compliance-notes.md) | The reasoning behind each guardrail and what pattern checks can't catch |
| [Decisions (ADRs)](docs/decisions/) | DuckDB · retry policy · rules + LLM · synthetic data |
| [Roadmap](docs/roadmap.md) | The backlog, also tracked as GitHub Issues |

<details>
<summary><b>📖 Metrics glossary</b></summary>

| Metric | Definition |
|---|---|
| Payment success rate | Payments that end settled ÷ payments sent (after retries) |
| First-attempt success | Payments settled on attempt 1 ÷ payments sent |
| Settlement time | First send → settlement, settled payments only (median, p90) |
| Return rate (per attempt) | Returned attempts ÷ all attempts; by reason in the dashboard |
| Time to resolve failed transfers | First send → settled on retry or resolved by a human, for payments with ≥ 1 return |
| Recon error rate | (unmatched payments + unmatched statement lines + matches with an amount difference) ÷ (expected payments + statement lines − reversal-pair lines) |
| DPD bucket | current, 1-30, 31-60, 61-90, 90+ (plus charged-off at 180+ DPD) |
| Roll rate | Share of accounts in bucket X at month t that are in bucket Y at t+1 |
| Cure rate | Share of delinquent accounts at month t that are current at t+1 |
| Recovery rate | Cash collected after an account first hits 90+ ÷ balance at that point |
| Days to resolution | Missed due date → payment that made the account current (open episodes censored) |
| Vintage curve | Share of an origination cohort ever 30+ DPD by months on book |
| PTP kept rate | Promises where next payment ≥ 95% of the promised amount ÷ resolved promises |
| Risk score | Sum of feature points (0-100) from `config/early_warning.yaml` |

</details>

<details>
<summary><b>🗂 What's where</b></summary>

```
Home.py, pages/        Streamlit UI (5 pages)
core/                  Domain logic: clabe, payments, spei_sim, retry, recon, portfolio,
                       early_warning, treatment, nudges, compliance, ptp
sql/                   Every metric as a plain DuckDB query
config/                Business rules in YAML
data/                  Public bank catalog + seeded sample payment file
docs/                  One-pagers, ADRs, experiment design, compliance notes, roadmap
tests/                 Unit tests for core/ + smoke tests for every page
```

</details>

---

## 🤖 Built with AI coding tools

I built this with Claude Code as a pair programmer. I set the product scope, constraints and
acceptance criteria. The assistant prototyped each module on its own feature branch, and I
reviewed every diff. I challenged the domain calls (which returns are retryable, what counts
as a cure, what the guardrails must block) and asked for changes. Tests and CI are the
contract: nothing merges without ruff, pytest and the coverage gate passing. Two real bugs
were caught that way and are documented in the PR history.

## ⚠️ Limitations and synthetic data

- **All data is synthetic** and seeded. Names are obviously fake ("PyME Demo 0042",
  "Demo Finanzas"); the only real names are public bank names in `data/banks.csv`, a subset
  to verify against Banxico.
- **SPEI return reasons are illustrative labels**, not Banxico's official catalog or codes.
- Settlement latency, human resolution time and the bank statement are simulated. The
  portfolio has no interest or fees, and balances freeze at 90+ DPD.
- **Compliance rules are a high-level reading of CONDUSEF's collection rules**, implemented
  as patterns. This is not legal advice; verify before any real use.
- No real SPEI, WhatsApp, email or dialer integrations. State lives in the browser session.
- **Live demo:** not deployed yet (tracked in the roadmap).

<div align="center">

**MIT licensed** · Built by [manuel-lomelin](https://github.com/manuel-lomelin) · Product Lead, Mexican fintech

</div>

"""Compliance guardrails for collection messages. Every draft passes through `check_draft`.

Rules (config/compliance.yaml):
- contact_window: send time must be inside the allowed window in the debtor's local time
- no_threats_or_abuse: no threatening, abusive, third-party-pressure or fake-authority text
- identifies_sender: the lender's name appears in the message
- includes_amount: the exact amount owed appears in the message
- includes_payment_option: a CLABE, payment reference or payment link appears
- frequency_cap: daily / weekly contact caps (and the treatment stage's weekly cap)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from core.config import load_config


@dataclass(frozen=True)
class RuleResult:
    rule: str
    passed: bool
    detail: str


@dataclass
class ComplianceReport:
    results: list[RuleResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failed_rules(self) -> list[str]:
        return [r.rule for r in self.results if not r.passed]


def fold(text: str) -> str:
    """Lowercase and strip accents so 'Cárcel' and 'carcel' match the same pattern."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def format_mxn(amount: float) -> str:
    return f"${amount:,.2f}"


def _parse_hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def check_contact_window(send_at: datetime, tz: str, cfg: dict) -> RuleResult:
    if send_at.tzinfo is None:
        raise ValueError("send_at must be timezone-aware")
    local = send_at.astimezone(ZoneInfo(tz))
    start, end = (
        _parse_hhmm(cfg["contact_window"]["start"]),
        _parse_hhmm(cfg["contact_window"]["end"]),
    )
    ok = start <= local.time() < end
    return RuleResult(
        "contact_window",
        ok,
        f"{local:%Y-%m-%d %H:%M} {tz} is {'inside' if ok else 'outside'} "
        f"{cfg['contact_window']['start']}-{cfg['contact_window']['end']}",
    )


def check_language(text: str, cfg: dict) -> RuleResult:
    folded = fold(text)
    hits = []
    for category, patterns in cfg["forbidden_patterns"].items():
        for pattern in patterns:
            m = re.search(pattern, folded)
            if m:
                hits.append(f"{category}: '{m.group(0)}'")
    return RuleResult(
        "no_threats_or_abuse", not hits, "; ".join(hits) if hits else "no forbidden language"
    )


def check_sender(text: str, cfg: dict) -> RuleResult:
    ok = fold(cfg["sender_name"]) in fold(text)
    return RuleResult(
        "identifies_sender", ok, f"sender '{cfg['sender_name']}' " + ("found" if ok else "missing")
    )


def check_amount(text: str, amount: float) -> RuleResult:
    expected = format_mxn(amount)
    # Accept the amount with or without the currency sign / thousands separator.
    variants = {expected, expected[1:], expected.replace(",", ""), expected[1:].replace(",", "")}
    ok = any(v in text for v in variants)
    return RuleResult("includes_amount", ok, f"{expected} " + ("found" if ok else "missing"))


def check_payment_option(text: str, cfg: dict) -> RuleResult:
    ok = any(re.search(p, text) for p in cfg["payment_option_patterns"])
    return RuleResult(
        "includes_payment_option",
        ok,
        "payment option " + ("found" if ok else "missing (CLABE, referencia or link)"),
    )


def check_frequency(
    send_at: datetime, history: list[datetime], cfg: dict, stage_weekly_cap: int | None = None
) -> RuleResult:
    caps = cfg["frequency_caps"]
    day = sum(1 for t in history if send_at - timedelta(days=1) < t <= send_at)
    week = sum(1 for t in history if send_at - timedelta(days=7) < t <= send_at)
    weekly_cap = caps["per_week"]
    if stage_weekly_cap is not None:
        weekly_cap = min(weekly_cap, stage_weekly_cap)
    ok = day < caps["per_day"] and week < weekly_cap
    return RuleResult(
        "frequency_cap",
        ok,
        f"{day} contact(s) in 24h (cap {caps['per_day']}), {week} in 7d (cap {weekly_cap})",
    )


def check_draft(
    text: str,
    *,
    amount: float,
    send_at: datetime,
    timezone: str,
    history: list[datetime] | None = None,
    stage_weekly_cap: int | None = None,
    cfg: dict | None = None,
) -> ComplianceReport:
    cfg = cfg or load_config("compliance")
    return ComplianceReport(
        [
            check_contact_window(send_at, timezone, cfg),
            check_language(text, cfg),
            check_sender(text, cfg),
            check_amount(text, amount),
            check_payment_option(text, cfg),
            check_frequency(send_at, history or [], cfg, stage_weekly_cap),
        ]
    )

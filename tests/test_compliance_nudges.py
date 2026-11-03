from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from core import nudges
from core.clabe import is_valid_clabe
from core.compliance import check_draft, fold, format_mxn
from core.nudges import (
    AccountContext,
    ContactLog,
    Draft,
    llm_draft,
    prepare_and_check,
    seed_contact_log,
    template_draft,
)
from core.portfolio import generate_portfolio
from core.ptp import add_promise, resolve_promise, summarize

MX = ZoneInfo("America/Mexico_City")
NOON = datetime(2026, 10, 1, 12, 0, tzinfo=MX)


def ctx(stage="nudge", channel="whatsapp", tz="America/Mexico_City"):
    return AccountContext(
        "A0042", "Ana", "PyME Demo 0042 SA de CV", 12345.6, stage, channel, tz, "2026-10-10", 15
    )


def results(report):
    return {r.rule: r.passed for r in report.results}


@pytest.mark.parametrize(
    ("stage", "channel"),
    [
        ("reminder", "whatsapp"),
        ("nudge", "whatsapp"),
        ("call", "phone"),
        ("call", "whatsapp"),
        ("payment_plan", "email"),
        ("agency_handoff", "email"),
    ],
)
def test_every_template_passes_compliance(stage, channel):
    c = ctx(stage, channel)
    draft = template_draft(c)
    report = prepare_and_check(c, draft, NOON, ContactLog())
    assert report.passed, report.results
    assert "$12,345.60" in draft.text and c.clabe in draft.text


def test_unknown_stage_or_channel():
    with pytest.raises(ValueError):
        template_draft(ctx(stage="no_action"))
    # Unknown channel falls back to the stage's first template.
    assert template_draft(ctx("nudge", "sms")).text


def test_collection_clabe_is_valid_and_reference_numeric():
    c = ctx()
    assert is_valid_clabe(c.clabe) and c.clabe.startswith("646")
    assert c.reference == "0000042"


@pytest.mark.parametrize(
    ("hour", "minute", "ok"), [(6, 59, False), (7, 0, True), (21, 59, True), (22, 0, False)]
)
def test_contact_window_edges(hour, minute, ok):
    send = datetime(2026, 10, 1, hour, minute, tzinfo=MX)
    text = template_draft(ctx()).text
    assert (
        results(check_draft(text, amount=12345.6, send_at=send, timezone="America/Mexico_City"))[
            "contact_window"
        ]
        is ok
    )


def test_contact_window_uses_debtor_local_time():
    # 07:30 in Mexico City is 06:30 in Tijuana (outside the window there).
    send = datetime(2026, 10, 1, 7, 30, tzinfo=MX)
    text = template_draft(ctx()).text
    assert not results(check_draft(text, amount=12345.6, send_at=send, timezone="America/Tijuana"))[
        "contact_window"
    ]


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        check_draft("x", amount=1, send_at=datetime(2026, 1, 1, 12), timezone="America/Cancun")


@pytest.mark.parametrize(
    "bad",
    [
        "Si no paga hoy, irá a la CÁRCEL.",
        "Vamos a informar a su familia y a sus vecinos.",
        "Recibirá una orden de aprehensión del juzgado.",
        "Es usted un ratero.",
        "Embargaremos sus bienes hoy mismo.",
        "Atengase a las consecuencias.",
    ],
)
def test_threats_and_abuse_are_blocked(bad):
    text = template_draft(ctx()).text + " " + bad
    report = check_draft(text, amount=12345.6, send_at=NOON, timezone="America/Mexico_City")
    assert not report.passed
    assert "no_threats_or_abuse" in report.failed_rules


def test_missing_sender_amount_and_payment_option():
    report = check_draft(
        "Hola, tiene un saldo pendiente.", amount=500, send_at=NOON, timezone="America/Mexico_City"
    )
    assert set(report.failed_rules) == {
        "identifies_sender",
        "includes_amount",
        "includes_payment_option",
    }


def test_amount_accepts_unformatted_variant():
    text = "Demo Finanzas: saldo 1234.50, referencia 1"
    assert check_draft(text, amount=1234.5, send_at=NOON, timezone="America/Mexico_City").passed


def test_frequency_caps():
    c = ctx()
    log = ContactLog()
    draft = template_draft(c)
    assert log.record(c, draft, prepare_and_check(c, draft, NOON, log), NOON)
    # Second contact the same day breaks the daily cap and is logged as blocked.
    later = NOON + timedelta(hours=2)
    report = prepare_and_check(c, draft, later, log)
    assert report.failed_rules == ["frequency_cap"]
    assert not log.record(c, draft, report, later)
    assert list(log.blocked_frame()["failed_rules"]) == ["frequency_cap"]
    # The stage's weekly cap can be tighter than the global one.
    tomorrow = NOON + timedelta(days=1, hours=1)
    assert prepare_and_check(c, draft, tomorrow, log).passed
    assert not prepare_and_check(c, draft, tomorrow, log, stage_weekly_cap=1).passed
    assert len(log.sent_frame()) == 1


def test_fold_and_format():
    assert fold("CÁRCEL Ñu") == "carcel nu"
    assert format_mxn(1234567.891) == "$1,234,567.89"


def test_llm_without_key_falls_back_to_template(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert not nudges.llm_available()
    draft = llm_draft(ctx())
    assert draft.source == "llm_fallback_template"
    assert draft.text == template_draft(ctx()).text


class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _Response:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_Block(text)] if text else []
        self.stop_reason = stop_reason
        self.model = "claude-opus-5-5"


class FakeClient:
    def __init__(self, response=None, error=None):
        self.calls = []
        self._response, self._error = response, error
        self.beta = self
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._response


def test_llm_draft_uses_claude_and_is_still_checked():
    text = (
        "Hola Ana, te escribe Demo Finanzas. Tu saldo vencido es $12,345.60. Paga por "
        "SPEI a la CLABE 646180000000000425 con referencia 0000042. Si no pagas, cárcel."
    )
    client = FakeClient(_Response(text))
    draft = llm_draft(ctx(), client=client)
    assert draft.source == "llm"
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default"
    assert "$12,345.60" in call["messages"][0]["content"]
    # The LLM text is not trusted: the threat is caught by the same guardrails.
    report = prepare_and_check(ctx(), draft, NOON, ContactLog())
    assert report.failed_rules == ["no_threats_or_abuse"]


@pytest.mark.parametrize(
    ("client", "note"),
    [
        (FakeClient(_Response("x", stop_reason="refusal")), "LLM refused"),
        (FakeClient(_Response("")), "LLM returned no text"),
        (FakeClient(error=RuntimeError("boom")), "LLM error: RuntimeError"),
    ],
)
def test_llm_failures_fall_back(client, note):
    draft = llm_draft(ctx(), client=client)
    assert draft.source == "llm_fallback_template" and draft.note == note


def test_llm_available_with_key(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    assert nudges.llm_available()


def test_llm_unavailable_without_sdk(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_anthropic(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    monkeypatch.setattr(builtins, "__import__", no_anthropic)
    assert not nudges.llm_available()


def test_seed_contact_log_only_active_accounts():
    wl = pd.DataFrame(
        {
            "account_id": ["A1", "A2"],
            "stage": ["nudge", "no_action"],
            "channel": ["whatsapp", "none"],
        }
    )
    log = seed_contact_log(wl, NOON, max_recent=3, seed=1)
    assert {c["account_id"] for c in log.sent} <= {"A1"}
    assert all(NOON - timedelta(days=7) < t < NOON for t in log.history("A1"))


def test_manual_draft_passes_through_checker():
    draft = Draft("Demo Finanzas: debe $10.00. Referencia 1.", source="manual")
    report = prepare_and_check(ctx(), draft, NOON, ContactLog())
    assert "includes_amount" in report.failed_rules  # amount is 12,345.60, not 10.00


def test_ptp_tracker_roundtrip():
    promises = generate_portfolio(n_accounts=120, seed=3).promises
    n = len(promises)
    added = add_promise(promises, "A0001", 1000, date(2026, 10, 15), date(2026, 10, 1), 20)
    assert len(added) == n + 1 and added.iloc[-1]["outcome"] == "pending"
    pid = added.iloc[-1]["promise_id"]
    kept = resolve_promise(added, pid, 960)
    assert kept.iloc[-1]["outcome"] == "kept"
    assert resolve_promise(added, pid, 100).iloc[-1]["outcome"] == "broken"
    with pytest.raises(ValueError):
        resolve_promise(kept, pid, 1000)
    with pytest.raises(KeyError):
        resolve_promise(kept, "nope", 1)
    with pytest.raises(ValueError):
        add_promise(promises, "A1", 0, date(2026, 10, 15), date(2026, 10, 1), 0)
    with pytest.raises(ValueError):
        add_promise(promises, "A1", 10, date(2026, 9, 1), date(2026, 10, 1), 0)
    s = summarize(kept)
    total = s["by_bucket"][s["by_bucket"]["bucket_at_promise"].isna()].iloc[0]
    assert total["promises"] == n + 1
    assert 0 < total["kept_rate"] <= 1
    assert len(s["by_month"]) >= 1

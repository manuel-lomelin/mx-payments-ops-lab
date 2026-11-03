import io
from datetime import datetime, timedelta

import pandas as pd
import pytest

from core.account_verification import (
    BankAccount,
    CobreOwnershipLookup,
    Lookup,
    Outcome,
    OwnershipLookupError,
    PennyResult,
    SimulatedOwnershipLookup,
    SimulatedPennyDrop,
    VerificationCache,
    in_response_window,
    is_valid_rfc,
    load_registry,
    next_window_open,
    verification_summary,
    verify_accounts,
)
from core.billpay_demo import registry_for, run_pipeline, sample_run
from core.clabe import build_clabe
from core.config import load_config
from core.payments import preflight, read_payments_csv, to_instructions
from core.sample_data import generate_bank_registry, generate_payment_batch, supplier_rfc
from core.spei_sim import SimConfig, run_batch

MONDAY_9 = datetime(2026, 3, 2, 9, 0)
RFC_A = "PDE100324DKU"
RFC_B = "TDE070914DHR"
GOOD = build_clabe("012", "180", "00012345678")
OTHER = build_clabe("072", "180", "00087654321")
LOOKUP_CFG = load_config("account_verification")["ownership_lookup"]


def report_for(rows):
    base = {
        "beneficiary": "Proveedor Demo 001 SA de CV",
        "clabe": GOOD,
        "amount_mxn": "100.00",
        "reference": "1234567",
        "concept": "Pago",
        "beneficiary_rfc": RFC_A,
    }
    return preflight(pd.DataFrame([{**base, **r} for r in rows]))


def registry(*accounts):
    return {a.clabe: a for a in accounts}


def account(clabe=GOOD, rfc=RFC_A, status="active"):
    return BankAccount(clabe, "PROVEEDOR DEMO 001 SA DE CV", rfc, status)


def only_infra_failures():
    sim = SimConfig.from_config(p_settled=0, p_returned=1, p_pending=0)
    sim.reasons = [r for r in sim.reasons if r["retryable"]]
    return sim


def no_infra_failures():
    return SimConfig.from_config(p_settled=1, p_returned=0, p_pending=0)


def penny(reg, **kw):
    return SimulatedPennyDrop(reg, sim=no_infra_failures(), **kw)


class FixedLookup:
    """Lookup that always answers the same outcome immediately."""

    name = "fixed"

    def __init__(self, outcome=Outcome.MATCHED, error=None):
        self.outcome, self.error, self.calls = outcome, error, 0

    def submit(self, clabe, holder_id, external_id, at):
        self.calls += 1
        if self.error:
            raise self.error
        return Lookup(clabe, holder_id, self.name, f"av_{self.calls}", self.outcome, at, at)

    def refresh(self, lookup, at):  # pragma: no cover - never processing
        return lookup


# ------------------------------------------------------------------ RFC + registry


@pytest.mark.parametrize(
    ("rfc", "ok"),
    [
        ("PDE100324DKU", True),
        ("pde100324dku", True),
        ("GOMA800101AB1", True),
        ("PDE10032DKU", False),
        ("", False),
        (None, False),
        ("PD100324DKU", False),
    ],
)
def test_rfc_format(rfc, ok):
    assert is_valid_rfc(rfc) is ok


def test_sample_rfcs_are_stable_and_valid():
    assert supplier_rfc("Proveedor Demo 001 SA de CV") == supplier_rfc(
        "Proveedor Demo 001 SA de CV"
    )
    batch = generate_payment_batch(n=60, seed=3)
    assert batch["beneficiary_rfc"].map(is_valid_rfc).all()


def test_generated_registry_has_every_defect_type_and_is_seeded():
    batch = generate_payment_batch(n=400, seed=4)
    a, b = generate_bank_registry(batch, seed=1), generate_bank_registry(batch, seed=1)
    pd.testing.assert_frame_equal(a, b)
    assert set(a["status"]) == {"active", "blocked", "cancelled"}
    assert (a["owner_name"] == "TERCERO DEMO SA DE CV").any()
    assert a["clabe"].nunique() < batch["clabe"].nunique()  # some accounts do not exist


# ------------------------------------------------------------------ penny drop


@pytest.mark.parametrize(
    ("reg", "reason"),
    [
        ({}, "NONEXISTENT_ACCOUNT"),
        ({GOOD: account(status="blocked")}, "BLOCKED_ACCOUNT"),
        ({GOOD: account(status="cancelled")}, "CANCELLED_ACCOUNT"),
    ],
)
def test_penny_returns_for_account_problems(reg, reason):
    res = penny(reg).send(GOOD, MONDAY_9)
    assert (res.status, res.reason, res.cep) == ("returned", reason, None)


def test_penny_settles_with_cep_owner_data():
    res = penny({GOOD: account()}).send(GOOD, MONDAY_9)
    assert res.status == "settled"
    assert res.cep.beneficiary_rfc == RFC_A
    assert res.cep.amount_mxn == 0.01
    assert res.cep.tracking_key.startswith("PENNY")


def test_penny_retries_infrastructure_failures_only():
    res = SimulatedPennyDrop({GOOD: account()}, sim=only_infra_failures()).send(GOOD, MONDAY_9)
    assert res.status == "returned"
    assert res.reason in {"RECEIVER_UNAVAILABLE", "TIMEOUT"}
    assert res.retries_exhausted and res.attempts == 3


# ------------------------------------------------------------------ decisions


def test_happy_path_verified_and_cached():
    cache = VerificationCache()
    lookup = FixedLookup()
    out = verify_accounts(report_for([{}]), penny({GOOD: account()}), MONDAY_9, lookup, cache)
    row = out.iloc[0]
    assert (row["decision"], row["check"], row["cep_rfc"]) == (
        "verified",
        "penny_and_rfc_match",
        RFC_A,
    )
    assert row["penny_cost_mxn"] == 0.01 and row["lookups"] == 1
    again = verify_accounts(report_for([{}]), penny({GOOD: account()}), MONDAY_9, lookup, cache)
    assert again.iloc[0]["check"] == "reused" and lookup.calls == 1


def test_verified_pair_expires():
    cache = VerificationCache()
    verify_accounts(report_for([{}]), penny({GOOD: account()}), MONDAY_9, FixedLookup(), cache)
    later = MONDAY_9 + timedelta(days=200)
    out = verify_accounts(report_for([{}]), penny({GOOD: account()}), later, FixedLookup(), cache)
    assert out.iloc[0]["check"] == "penny_and_rfc_match"


def test_wrong_owner_blocks_and_stays_blocked():
    cache = VerificationCache()
    reg = {GOOD: account(rfc=RFC_B)}
    out = verify_accounts(report_for([{}]), penny(reg), MONDAY_9, FixedLookup(), cache)
    assert (out.iloc[0]["decision"], out.iloc[0]["check"]) == ("block", "wrong_owner")
    assert "fraud" in out.iloc[0]["next_action"]
    again = verify_accounts(report_for([{}]), penny(reg), MONDAY_9, FixedLookup(), cache)
    assert (again.iloc[0]["decision"], again.iloc[0]["check"]) == ("block", "previously_blocked")
    assert again.iloc[0]["penny_cost_mxn"] == 0


def test_returned_penny_blocks_and_costs_nothing():
    out = verify_accounts(report_for([{}]), penny({}), MONDAY_9, FixedLookup())
    row = out.iloc[0]
    assert (row["decision"], row["check"], row["penny_reason"]) == (
        "block",
        "penny_returned",
        "NONEXISTENT_ACCOUNT",
    )
    assert row["penny_cost_mxn"] == 0 and row["lookups"] == 0


def test_exhausted_infra_retries_hold():
    drop = SimulatedPennyDrop({GOOD: account()}, sim=only_infra_failures())
    out = verify_accounts(report_for([{}]), drop, MONDAY_9)
    assert (out.iloc[0]["decision"], out.iloc[0]["check"]) == ("hold", "penny_retries_exhausted")


def test_lookup_disagreeing_with_penny_holds():
    out = verify_accounts(
        report_for([{}]), penny({GOOD: account()}), MONDAY_9, FixedLookup(Outcome.UNMATCHED)
    )
    assert (out.iloc[0]["decision"], out.iloc[0]["check"]) == ("hold", "signals_disagree")


@pytest.mark.parametrize(
    "lookup",
    [
        FixedLookup(Outcome.UNRESOLVED),
        FixedLookup(Outcome.FAILED),
        FixedLookup(error=OwnershipLookupError("down")),
        None,
    ],
)
def test_penny_is_primary_when_lookup_is_inconclusive(lookup):
    out = verify_accounts(report_for([{}]), penny({GOOD: account()}), MONDAY_9, lookup)
    assert out.iloc[0]["decision"] == "verified"


def test_lookup_can_be_disabled():
    cfg = load_config("account_verification")
    cfg["ownership_lookup"]["enabled"] = False
    lookup = FixedLookup(Outcome.UNMATCHED)
    out = verify_accounts(report_for([{}]), penny({GOOD: account()}), MONDAY_9, lookup, cfg=cfg)
    assert out.iloc[0]["decision"] == "verified" and lookup.calls == 0


def test_invalid_or_missing_rfc_holds_without_spending():
    report = report_for([{"beneficiary_rfc": "XX"}])
    assert "RFC missing or malformed" in report.loc[0, "issues"]
    out = verify_accounts(report, penny({GOOD: account()}), MONDAY_9, FixedLookup())
    assert (out.iloc[0]["decision"], out.iloc[0]["check"]) == ("hold", "invalid_rfc")
    no_column = report_for([{}]).drop(columns="beneficiary_rfc")
    out = verify_accounts(no_column, penny({GOOD: account()}), MONDAY_9)
    assert out.iloc[0]["check"] == "invalid_rfc"


def test_rows_sharing_a_pair_share_one_check_and_blocked_rows_are_skipped():
    report = report_for([{"reference": "1"}, {"reference": "2"}, {"clabe": "123"}])
    lookup = FixedLookup()
    out = verify_accounts(report, penny({GOOD: account()}), MONDAY_9, lookup)
    assert list(out["payment_id"]) == ["P00001", "P00002"]  # P00003 failed filter 1
    assert out.iloc[1]["check"] == "reused"  # verified by the first row
    assert out["penny_cost_mxn"].sum() == 0.01 and lookup.calls == 1
    # A held pair is not cached, so a second row reuses the first row's check.
    held = verify_accounts(
        report_for([{"reference": "1"}, {"reference": "2"}]),
        penny({GOOD: account()}),
        MONDAY_9,
        FixedLookup(Outcome.UNMATCHED),
    )
    assert list(held["check"]) == ["signals_disagree", "same pair as an earlier row"]
    assert held["penny_cost_mxn"].sum() == 0.01


def test_summary():
    reg = {GOOD: account()}
    report = report_for([{}, {"clabe": OTHER}])
    s = verification_summary(verify_accounts(report, penny(reg), MONDAY_9, FixedLookup()))
    assert s["verified"] == 1 and s["blocked"] == 1 and s["penny_returned"] == 1
    assert s["penny_cost_mxn"] == 0.01 and s["lookups"] == 1
    assert s["median_penny_seconds"] > 0


# ------------------------------------------------------------------ simulated lookup


@pytest.mark.parametrize(
    ("at", "inside"),
    [
        (datetime(2026, 3, 2, 6, 59), False),
        (datetime(2026, 3, 2, 7, 0), True),
        (datetime(2026, 3, 2, 18, 29), True),
        (datetime(2026, 3, 2, 18, 30), False),
        (datetime(2026, 3, 7, 15, 59), True),
        (datetime(2026, 3, 7, 16, 0), False),
    ],
)
def test_response_windows(at, inside):
    assert in_response_window(at, LOOKUP_CFG) is inside


def test_next_window_open():
    assert next_window_open(datetime(2026, 3, 2, 5, 0), LOOKUP_CFG) == datetime(2026, 3, 2, 7, 0)
    assert next_window_open(datetime(2026, 3, 2, 19, 0), LOOKUP_CFG) == datetime(2026, 3, 3, 7, 0)
    inside = datetime(2026, 3, 2, 10, 0)
    assert next_window_open(inside, LOOKUP_CFG) == inside


def test_simulated_lookup_outcomes_and_latency():
    reg = registry(account(), account(clabe=OTHER, rfc=RFC_B))
    cfg = {**LOOKUP_CFG, "p_unresolved": 0}
    lookup = SimulatedOwnershipLookup(reg, cfg=cfg)
    pending = lookup.submit(GOOD, RFC_A, "x", MONDAY_9)
    assert pending.outcome == Outcome.PROCESSING and not pending.done
    assert lookup.refresh(pending, MONDAY_9).outcome == Outcome.PROCESSING
    done = lookup.refresh(pending, lookup.completion_time(pending))
    assert done.outcome == Outcome.MATCHED and done.completed_at > MONDAY_9
    other = lookup.submit(OTHER, RFC_A, "y", MONDAY_9)
    assert lookup.refresh(other, other.submitted_at + timedelta(days=2)).outcome == (
        Outcome.UNMATCHED
    )
    missing = lookup.submit(build_clabe("014", "180", "1"), RFC_A, "z", MONDAY_9)
    failed = lookup.refresh(missing, MONDAY_9 + timedelta(days=2))
    assert (failed.outcome, failed.code) == (Outcome.FAILED, "F006")


def test_simulated_lookup_unresolved_and_late_submissions_wait_for_window():
    lookup = SimulatedOwnershipLookup(registry(account()), cfg={**LOOKUP_CFG, "p_unresolved": 1})
    late = lookup.submit(GOOD, RFC_A, "x", datetime(2026, 3, 2, 21, 0))
    assert lookup.completion_time(late) >= datetime(2026, 3, 3, 7, 0)
    assert lookup.refresh(late, datetime(2026, 3, 4)).outcome == Outcome.UNRESOLVED


# ------------------------------------------------------------------ Cobre client


class FakeCobre:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        return self.responses.pop(0)


AUTH = (200, {"access_token": "tok1", "type": "Bearer", "expiration_time": 1200})


def cobre(responses):
    fake = FakeCobre(responses)
    return CobreOwnershipLookup("user", "secret", transport=fake), fake


def test_cobre_submit_sends_documented_payload():
    client, fake = cobre([AUTH, (201, {"id": "av_1", "status": {"state": "processing"}})])
    res = client.submit(GOOD, RFC_A, "P00001", MONDAY_9)
    assert res.outcome == Outcome.PROCESSING and res.verification_id == "av_1"
    method, url, _, body = fake.calls[0]
    assert (method, url, body) == (
        "POST",
        "https://api.cobre.co/v1/auth",
        {"user_id": "user", "secret": "secret"},
    )
    method, url, headers, body = fake.calls[1]
    assert (method, url) == ("POST", "https://api.cobre.co/v1/account_verifications")
    assert headers == {"Authorization": "Bearer tok1"}
    assert body == {
        "model": "mex_acc_ownership_1",
        "verification_request": {
            "account_number": GOOD,
            "account_type": "clabe",
            "account_holder_id_number": RFC_A,
            "account_holder_id_type": "rfc",
        },
        "external_id": "P00001",
    }


@pytest.mark.parametrize(
    ("payload", "outcome", "code"),
    [
        (
            {
                "status": {"state": "completed", "code": "-"},
                "verification_response": {"verification_result": "matched"},
            },
            Outcome.MATCHED,
            "",
        ),
        (
            {
                "status": {"state": "completed"},
                "verification_response": {"verification_result": "unmatched"},
            },
            Outcome.UNMATCHED,
            "",
        ),
        ({"status": {"state": "completed"}, "verification_response": {}}, Outcome.UNRESOLVED, ""),
        ({"status": {"state": "failed", "code": "F006"}}, Outcome.FAILED, "F006"),
    ],
)
def test_cobre_refresh_parses_states(payload, outcome, code):
    client, fake = cobre([AUTH, (200, {"id": "av_1", **payload})])
    pending = Lookup(GOOD, RFC_A, "cobre", "av_1", Outcome.PROCESSING, MONDAY_9)
    res = client.refresh(pending, MONDAY_9 + timedelta(minutes=10))
    assert (res.outcome, res.code, res.submitted_at) == (outcome, code, MONDAY_9)
    assert fake.calls[1][:2] == ("GET", "https://api.cobre.co/v1/account_verifications/av_1")


def test_cobre_reauthenticates_once_on_401():
    client, fake = cobre(
        [
            AUTH,
            (401, {"message": "Unauthorized"}),
            (200, {"access_token": "tok2"}),
            (201, {"id": "av_2"}),
        ]
    )
    assert client.submit(GOOD, RFC_A, "x", MONDAY_9).verification_id == "av_2"
    assert fake.calls[-1][2] == {"Authorization": "Bearer tok2"}


@pytest.mark.parametrize(
    "responses",
    [
        [(403, {"message": "Forbidden"})],
        [AUTH, (409, {"error_code": "G001"})],
        [AUTH, (401, {}), AUTH, (401, {})],
    ],
)
def test_cobre_errors_raise(responses):
    client, _ = cobre(responses)
    with pytest.raises(OwnershipLookupError):
        client.submit(GOOD, RFC_A, "x", MONDAY_9)


def test_cobre_from_env():
    assert CobreOwnershipLookup.from_env({}) is None
    client = CobreOwnershipLookup.from_env(
        {"COBRE_USER_ID": "u", "COBRE_SECRET": "s", "COBRE_BASE_URL": "https://sandbox.example/v1/"}
    )
    assert client.base_url == "https://sandbox.example/v1"


def test_cobre_error_in_pipeline_does_not_block_a_good_penny():
    client, _ = cobre([(500, {})])
    out = verify_accounts(report_for([{}]), penny({GOOD: account()}), MONDAY_9, client)
    assert out.iloc[0]["decision"] == "verified"
    assert out.iloc[0]["lookup_outcome"].startswith("provider_error")


def test_cobre_processing_result_is_polled_once():
    client, _ = cobre(
        [
            AUTH,
            (201, {"id": "av_1", "status": {"state": "processing"}}),
            (
                200,
                {
                    "id": "av_1",
                    "status": {"state": "completed"},
                    "verification_response": {"verification_result": "matched"},
                },
            ),
        ]
    )
    out = verify_accounts(report_for([{}]), penny({GOOD: account()}), MONDAY_9, client)
    assert out.iloc[0]["lookup_outcome"] == "matched"


# ------------------------------------------------------------------ simulator + demo


def test_without_reasons_moves_odds_to_settled():
    cfg = SimConfig.from_config()
    verified = cfg.without_reasons(cfg.prevented_by_verification)
    assert {r["id"] for r in verified.reasons}.isdisjoint(cfg.prevented_by_verification)
    assert verified.p_returned < cfg.p_returned
    assert verified.p_settled + verified.p_returned + verified.p_pending == pytest.approx(1)


def test_verified_payments_never_get_prevented_returns():
    cfg = SimConfig.from_config(p_settled=0.2, p_returned=0.8, p_pending=0)
    report = report_for([{"reference": str(i), "amount_mxn": f"{100 + i}.00"} for i in range(60)])
    reg = {GOOD: account()}
    v = verify_accounts(report, penny(reg), MONDAY_9, FixedLookup())
    run = run_batch(to_instructions(report, v), cfg=cfg)
    assert run.payments["account_verified"].all()
    assert set(run.attempts["reason"].dropna()).isdisjoint(cfg.prevented_by_verification)


def test_to_instructions_sends_only_verified():
    report = report_for([{}, {"clabe": OTHER}])
    v = verify_accounts(report, penny({GOOD: account()}), MONDAY_9, FixedLookup())
    ins = to_instructions(report, v)
    assert [i.payment_id for i in ins] == ["P00001"]
    assert ins[0].account_verified and ins[0].beneficiary_rfc == RFC_A
    assert not any(i.account_verified for i in to_instructions(report))


def test_sample_pipeline_blocks_bad_accounts_and_improves_success():
    with_v, without = sample_run(verify=True), sample_run(verify=False)
    s = verification_summary(with_v.verification)
    assert s["penny_returned"] > 0 and s["wrong_owner"] > 0
    rate = lambda run: (run.batch.payments["final_status"] == "settled").mean()  # noqa: E731
    assert rate(with_v) > rate(without)


def test_uploaded_files_get_a_synthetic_registry():
    df = read_payments_csv(io.StringIO(generate_payment_batch(n=30, seed=9).to_csv(index=False)))
    reg = registry_for(df, is_sample=False)
    assert len(reg) > 0 and all(isinstance(a, BankAccount) for a in reg.values())
    no_rfc = registry_for(df.drop(columns="beneficiary_rfc"), is_sample=False)
    assert len(no_rfc) > 0
    demo = run_pipeline(preflight(df), reg)
    assert demo.verification is not None and len(demo.batch.payments) > 0


def test_load_registry_roundtrip():
    frame = generate_bank_registry(generate_payment_batch(n=20, seed=2))
    reg = load_registry(frame)
    assert set(reg) == set(frame["clabe"])


def test_penny_result_type():
    assert PennyResult("settled", None, 1, MONDAY_9, MONDAY_9).cep is None


def test_urllib_transport_paths(monkeypatch):
    import urllib.error

    from core import account_verification as av

    class Resp:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"id": "av_9"}'

    seen = {}

    def ok(req, timeout):
        seen.update(
            url=req.full_url,
            method=req.get_method(),
            body=req.data,
            auth=req.get_header("Authorization"),
        )
        return Resp()

    monkeypatch.setattr(av.urllib.request, "urlopen", ok)
    assert av._urllib_transport(
        "POST", "https://x/v1/a", {"Authorization": "Bearer t"}, {"k": 1}
    ) == (201, {"id": "av_9"})
    assert seen == {
        "url": "https://x/v1/a",
        "method": "POST",
        "body": b'{"k": 1}',
        "auth": "Bearer t",
    }

    def http_error(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 409, "Conflict", {}, io.BytesIO(b'{"error_code": "G001"}')
        )

    monkeypatch.setattr(av.urllib.request, "urlopen", http_error)
    assert av._urllib_transport("GET", "https://x", {}, None) == (409, {"error_code": "G001"})

    def http_error_html(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 502, "Bad", {}, io.BytesIO(b"<html>"))

    monkeypatch.setattr(av.urllib.request, "urlopen", http_error_html)
    assert av._urllib_transport("GET", "https://x", {}, None) == (502, {})

    def down(req, timeout):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(av.urllib.request, "urlopen", down)
    with pytest.raises(OwnershipLookupError, match="unreachable"):
        av._urllib_transport("GET", "https://x", {}, None)

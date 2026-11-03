"""Filter 2: verify a supplier's account before its first real payment.

Filter 1 (core.clabe + core.payments) proves a CLABE is well formed. It cannot prove the
account exists, accepts SPEI, or belongs to the supplier. Filter 2 does, in two steps:

2a. Penny drop. Send MXN 0.01 over SPEI. A return (devolución) means the account cannot
    receive money. A settled cent comes with a CEP (Banxico's proof of payment) that shows
    the beneficiary RFC as the receiving bank has it; it must match the invoice RFC.
2b. Ownership lookup. A no-money cross-check: ask the provider whether the CLABE belongs
    to the RFC (Cobre Account Verification, model mex_acc_ownership_1).

Decision for a new (CLABE, RFC) pair:
- penny returned (account problem)          -> block
- penny failed on infrastructure, retried    -> hold
- penny settled, CEP RFC != invoice RFC      -> block (wrong owner)
- penny settled + RFC match, lookup unmatched -> hold (signals disagree)
- penny settled + RFC match, otherwise        -> verified (penny is the primary proof)
Verified pairs are cached and reused, so each supplier account is checked once.

Everything runs against a synthetic bank registry by default. CobreOwnershipLookup is a
client for Cobre's API written from their public docs; it is not exercised against the
live API in this repository. A real penny drop would be a regular SPEI payout through the
provider plus a CEP lookup by tracking key; here it runs on the SPEI simulator.
"""

from __future__ import annotations

import json
import math
import random
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Protocol

import pandas as pd

from core.config import load_config
from core.payments import RFC_PATTERN
from core.retry import Action, RetryPolicy
from core.spei_sim import SimConfig, simulate_attempt


def normalize_rfc(value) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip().upper()


def is_valid_rfc(value) -> bool:
    return bool(RFC_PATTERN.match(normalize_rfc(value)))


@dataclass(frozen=True)
class BankAccount:
    """What the receiving bank knows about an account (synthetic registry row)."""

    clabe: str
    owner_name: str
    owner_rfc: str
    status: str = "active"  # active | blocked | cancelled


def load_registry(df: pd.DataFrame) -> dict[str, BankAccount]:
    return {
        str(r.clabe): BankAccount(str(r.clabe), r.owner_name, r.owner_rfc, r.status)
        for r in df.itertuples()
    }


# ------------------------------------------------------------------ 2a. penny drop


@dataclass(frozen=True)
class Cep:
    """The fields of a CEP that matter for verification."""

    tracking_key: str
    beneficiary_name: str
    beneficiary_rfc: str
    amount_mxn: float
    settled_at: datetime


@dataclass(frozen=True)
class PennyResult:
    status: str  # settled | returned
    reason: str | None
    attempts: int
    sent_at: datetime
    resolved_at: datetime
    retries_exhausted: bool = False
    cep: Cep | None = None


class PennyDropProvider(Protocol):
    name: str

    def send(self, clabe: str, at: datetime) -> PennyResult: ...


ACCOUNT_STATUS_RETURNS = {"blocked": "BLOCKED_ACCOUNT", "cancelled": "CANCELLED_ACCOUNT"}


class SimulatedPennyDrop:
    """Penny drop on the SPEI simulator, answered from the synthetic bank registry.

    Unknown CLABE -> NONEXISTENT_ACCOUNT return; blocked/cancelled -> matching return;
    active accounts settle, except for infrastructure failures that the normal retry
    policy handles. A settled cent yields a CEP with the registry's owner data.
    """

    name = "simulated"

    def __init__(
        self,
        registry: dict[str, BankAccount],
        sim: SimConfig | None = None,
        policy: RetryPolicy | None = None,
        amount_mxn: float = 0.01,
        seed: int = 17,
    ):
        self.registry = registry
        base = sim or SimConfig.from_config()
        self.policy = policy or RetryPolicy.from_config()
        # An active account can only fail on infrastructure (retryable) reasons.
        account_reasons = [
            r["id"] for r in base.reasons if r["id"] not in self.policy.retryable_reasons
        ]
        self.sim = base.without_reasons(account_reasons)
        self.returned_latency = base.latency["returned"]
        self.amount = amount_mxn
        self.rng = random.Random(seed)
        self._count = 0

    def _lognormal(self, spec: dict) -> float:
        return self.rng.lognormvariate(math.log(spec["median"]), spec["sigma"])

    def send(self, clabe: str, at: datetime) -> PennyResult:
        account = self.registry.get(clabe)
        if account is None or account.status in ACCOUNT_STATUS_RETURNS:
            reason = (
                "NONEXISTENT_ACCOUNT" if account is None else ACCOUNT_STATUS_RETURNS[account.status]
            )
            done = at + timedelta(seconds=self._lognormal(self.returned_latency))
            return PennyResult("returned", reason, 1, at, done)

        sent_at, attempt = at, 0
        while True:
            attempt += 1
            res = simulate_attempt(self.rng, self.sim)
            resolved = sent_at + timedelta(seconds=res.latency_s)
            decision = self.policy.decide(res.status, res.reason, attempt)
            if decision.action == Action.RETRY:
                sent_at = resolved + timedelta(
                    seconds=self.policy.backoff_seconds(attempt, self.rng)
                )
                continue
            break
        if res.status != "settled":
            return PennyResult(
                "returned",
                res.reason,
                attempt,
                at,
                resolved,
                retries_exhausted=decision.retries_exhausted,
            )
        self._count += 1
        cep = Cep(
            f"PENNY{self._count:08d}", account.owner_name, account.owner_rfc, self.amount, resolved
        )
        return PennyResult("settled", None, attempt, at, resolved, cep=cep)


# ------------------------------------------------------------- 2b. ownership lookup


class Outcome(StrEnum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    UNRESOLVED = "unresolved"
    FAILED = "failed"  # provider state `failed`, e.g. code F006: account could not be validated
    PROCESSING = "processing"


@dataclass(frozen=True)
class Lookup:
    clabe: str
    holder_id: str
    provider: str
    verification_id: str
    outcome: Outcome
    submitted_at: datetime
    completed_at: datetime | None = None
    code: str = ""

    @property
    def done(self) -> bool:
        return self.outcome != Outcome.PROCESSING


class OwnershipLookupError(RuntimeError):
    """The lookup provider could not be reached or rejected the request."""


class OwnershipLookup(Protocol):
    name: str

    def submit(self, clabe: str, holder_id: str, external_id: str, at: datetime) -> Lookup: ...

    def refresh(self, lookup: Lookup, at: datetime) -> Lookup: ...


def _hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def _window(at: datetime, cfg: dict) -> dict:
    return cfg["response_window"]["business_day" if at.weekday() < 5 else "non_business_day"]


def in_response_window(at: datetime, cfg: dict) -> bool:
    w = _window(at, cfg)
    return _hhmm(w["start"]) <= at.time() < _hhmm(w["end"])


def next_window_open(at: datetime, cfg: dict) -> datetime:
    """`at` if inside a response window, otherwise when the next window opens."""
    candidate = at
    for _ in range(8):
        if in_response_window(candidate, cfg):
            return candidate
        start = datetime.combine(
            candidate.date(), _hhmm(_window(candidate, cfg)["start"]), candidate.tzinfo
        )
        candidate = start if candidate < start else start + timedelta(days=1)
    raise RuntimeError("no response window found")  # pragma: no cover


class SimulatedOwnershipLookup:
    """Answers from the synthetic registry with Cobre-like latency and response windows."""

    name = "simulated"

    def __init__(self, registry: dict[str, BankAccount], cfg: dict | None = None, seed: int = 13):
        self.registry = registry
        self.cfg = cfg or load_config("account_verification")["ownership_lookup"]
        self.rng = random.Random(seed)
        self._answers: dict[str, tuple[Outcome, datetime, str]] = {}

    def submit(self, clabe: str, holder_id: str, external_id: str, at: datetime) -> Lookup:
        vid = f"av_sim_{len(self._answers) + 1:05d}"
        lat = self.cfg["latency_seconds"]
        ready = at + timedelta(
            seconds=self.rng.lognormvariate(math.log(lat["median"]), lat["sigma"])
        )
        ready = next_window_open(ready, self.cfg)
        account = self.registry.get(clabe)
        if account is None:
            outcome, code = Outcome.FAILED, "F006"
        elif self.rng.random() < self.cfg["p_unresolved"]:
            outcome, code = Outcome.UNRESOLVED, ""
        elif account.owner_rfc.upper() != holder_id.upper():
            outcome, code = Outcome.UNMATCHED, ""
        else:
            outcome, code = Outcome.MATCHED, ""
        self._answers[vid] = (outcome, ready, code)
        return Lookup(clabe, holder_id, self.name, vid, Outcome.PROCESSING, at)

    def refresh(self, lookup: Lookup, at: datetime) -> Lookup:
        outcome, ready, code = self._answers[lookup.verification_id]
        if at < ready:
            return lookup
        return replace(lookup, outcome=outcome, completed_at=ready, code=code)

    def completion_time(self, lookup: Lookup) -> datetime:
        return self._answers[lookup.verification_id][1]


Transport = Callable[[str, str, dict, dict | None], tuple[int, dict]]


def _urllib_transport(method: str, url: str, headers: dict, body: dict | None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json", **headers}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read() or b"{}")
        except json.JSONDecodeError:
            payload = {}
        return exc.code, payload
    except urllib.error.URLError as exc:
        raise OwnershipLookupError(f"Cobre unreachable: {exc.reason}") from exc


class CobreOwnershipLookup:
    """Cobre Account Verification, model mex_acc_ownership_1 (CLABE + RFC/CURP).

    Per Cobre's docs: POST /auth (user_id, secret) returns a Bearer token; then
    POST /account_verifications and GET /account_verifications/{id}. Results are
    asynchronous: `status.state` goes processing -> completed | failed, and
    `verification_response.verification_result` is matched | unmatched | unresolved.
    """

    name = "cobre"
    DEFAULT_BASE_URL = "https://api.cobre.co/v1"

    def __init__(
        self,
        user_id: str,
        secret: str,
        base_url: str | None = None,
        transport: Transport | None = None,
        holder_id_type: str = "rfc",
    ):
        self.user_id, self.secret = user_id, secret
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.transport = transport or _urllib_transport
        self.holder_id_type = holder_id_type
        self._token: str | None = None

    @classmethod
    def from_env(cls, env) -> CobreOwnershipLookup | None:
        if not (env.get("COBRE_USER_ID") and env.get("COBRE_SECRET")):
            return None
        return cls(env["COBRE_USER_ID"], env["COBRE_SECRET"], env.get("COBRE_BASE_URL"))

    def _authenticate(self) -> str:
        status, body = self.transport(
            "POST", f"{self.base_url}/auth", {}, {"user_id": self.user_id, "secret": self.secret}
        )
        if status >= 300 or "access_token" not in body:
            raise OwnershipLookupError(f"Cobre auth failed ({status})")
        self._token = body["access_token"]
        return self._token

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        for attempt in (1, 2):
            token = self._token or self._authenticate()
            status, payload = self.transport(
                method, f"{self.base_url}{path}", {"Authorization": f"Bearer {token}"}, body
            )
            if status == 401 and attempt == 1:
                self._token = None  # expired token: re-authenticate once, then retry
                continue
            if status >= 300:
                code = payload.get("error_code") or payload.get("message") or ""
                raise OwnershipLookupError(f"Cobre {method} {path} -> {status} {code}".strip())
            return payload
        raise OwnershipLookupError("Cobre rejected the token twice")  # pragma: no cover

    def _parse(self, payload: dict, clabe: str, holder_id: str, at: datetime) -> Lookup:
        status = payload.get("status") or {}
        state = status.get("state", "processing")
        if state == "failed":
            outcome = Outcome.FAILED
        elif state == "completed":
            result = (payload.get("verification_response") or {}).get("verification_result")
            known = {o.value for o in (Outcome.MATCHED, Outcome.UNMATCHED, Outcome.UNRESOLVED)}
            outcome = Outcome(result) if result in known else Outcome.UNRESOLVED
        else:
            outcome = Outcome.PROCESSING
        code = status.get("code") or ""
        return Lookup(
            clabe,
            holder_id,
            self.name,
            payload.get("id", ""),
            outcome,
            at,
            completed_at=at if outcome != Outcome.PROCESSING else None,
            code="" if code == "-" else code,
        )

    def submit(self, clabe: str, holder_id: str, external_id: str, at: datetime) -> Lookup:
        payload = self._call(
            "POST",
            "/account_verifications",
            {
                "model": "mex_acc_ownership_1",
                "verification_request": {
                    "account_number": clabe,
                    "account_type": "clabe",
                    "account_holder_id_number": holder_id,
                    "account_holder_id_type": self.holder_id_type,
                },
                "external_id": external_id,
            },
        )
        return self._parse(payload, clabe, holder_id, at)

    def refresh(self, lookup: Lookup, at: datetime) -> Lookup:
        payload = self._call("GET", f"/account_verifications/{lookup.verification_id}")
        return replace(
            self._parse(payload, lookup.clabe, lookup.holder_id, at),
            submitted_at=lookup.submitted_at,
        )


# ------------------------------------------------------------------ combined policy

VERIFIED = "verified"
BLOCK = "block"
HOLD = "hold"


@dataclass
class VerificationCache:
    """Verified and blocked (CLABE, RFC) pairs.

    Verified pairs are trusted for `reuse_verified_days`. Blocked pairs stay blocked until
    the supplier record changes (a new CLABE or RFC is a new pair), so a known-bad account
    never gets another test transfer.
    """

    verified: dict[tuple[str, str], datetime] = field(default_factory=dict)
    blocked: dict[tuple[str, str], dict] = field(default_factory=dict)

    def is_verified(self, clabe: str, rfc: str, at: datetime, max_age: timedelta) -> bool:
        when = self.verified.get((clabe, rfc))
        return when is not None and at - when < max_age

    def add(self, clabe: str, rfc: str, at: datetime) -> None:
        self.verified[(clabe, rfc)] = at


def _action(key: str, cfg: dict) -> str:
    return " ".join(cfg["next_actions"][key].split())


def _run_lookup(
    lookup: OwnershipLookup, clabe: str, rfc: str, external_id: str, at: datetime
) -> Lookup | str:
    try:
        result = lookup.submit(clabe, rfc, external_id=external_id, at=at)
        if isinstance(lookup, SimulatedOwnershipLookup):
            return lookup.refresh(result, lookup.completion_time(result))
        return result if result.done else lookup.refresh(result, at)
    except OwnershipLookupError as exc:
        return f"provider_error: {exc}"


def verify_accounts(
    report: pd.DataFrame,
    penny: PennyDropProvider,
    at: datetime,
    lookup: OwnershipLookup | None = None,
    cache: VerificationCache | None = None,
    cfg: dict | None = None,
) -> pd.DataFrame:
    """Run filter 2 over every pre-flight row that is not blocked.

    One row per payment: decision (verified | block | hold), why, and the next action.
    Payments sharing a (CLABE, RFC) pair share one check.
    """
    cfg = cfg or load_config("account_verification")
    cache = cache if cache is not None else VerificationCache()
    max_age = timedelta(days=cfg["reuse_verified_days"])
    sendable = report[report["status"] != "blocked"]
    if "beneficiary_rfc" not in sendable.columns:
        sendable = sendable.assign(beneficiary_rfc="")

    checked: dict[tuple[str, str], dict] = {}
    rows = []
    for r in sendable.itertuples():
        rfc = normalize_rfc(r.beneficiary_rfc)
        key = (r.clabe, rfc)
        base = {
            "payment_id": r.payment_id,
            "beneficiary": r.beneficiary,
            "clabe": r.clabe,
            "bank_name": r.bank_name,
            "amount_mxn": r.amount,
            "beneficiary_rfc": rfc,
        }
        if not is_valid_rfc(rfc):
            rows.append(
                {
                    **base,
                    "decision": HOLD,
                    "check": "invalid_rfc",
                    "next_action": _action("invalid_rfc", cfg),
                }
            )
            continue
        if cache.is_verified(r.clabe, rfc, at, max_age):
            rows.append({**base, "decision": VERIFIED, "check": "reused"})
            continue
        if key in cache.blocked:
            rows.append(
                {
                    **base,
                    **cache.blocked[key],
                    "check": "previously_blocked",
                    "penny_cost_mxn": 0.0,
                    "lookups": 0,
                }
            )
            continue
        if key not in checked:
            checked[key] = _check_pair(r.clabe, rfc, r.payment_id, penny, lookup, at, cfg)
            if checked[key]["decision"] == VERIFIED:
                cache.add(r.clabe, rfc, checked[key]["verified_at"])
            elif checked[key]["decision"] == BLOCK:
                cache.blocked[key] = checked[key]
            rows.append({**base, **checked[key]})
        else:
            rows.append(
                {
                    **base,
                    **checked[key],
                    "check": "same pair as an earlier row",
                    "penny_cost_mxn": 0.0,
                    "lookups": 0,
                }
            )

    cols = [
        "payment_id",
        "beneficiary",
        "clabe",
        "bank_name",
        "amount_mxn",
        "beneficiary_rfc",
        "decision",
        "check",
        "penny_status",
        "penny_reason",
        "penny_attempts",
        "penny_seconds",
        "cep_tracking_key",
        "cep_rfc",
        "lookup_outcome",
        "lookup_minutes",
        "penny_cost_mxn",
        "lookups",
        "verified_at",
        "next_action",
    ]
    out = pd.DataFrame(rows).reindex(columns=cols)
    out["penny_cost_mxn"] = out["penny_cost_mxn"].fillna(0.0)
    out["lookups"] = out["lookups"].fillna(0).astype(int)
    return out


def _check_pair(
    clabe: str,
    rfc: str,
    external_id: str,
    penny: PennyDropProvider,
    lookup: OwnershipLookup | None,
    at: datetime,
    cfg: dict,
) -> dict:
    p = penny.send(clabe, at)
    row = {
        "penny_status": p.status,
        "penny_reason": p.reason,
        "penny_attempts": p.attempts,
        "penny_seconds": (p.resolved_at - p.sent_at).total_seconds(),
        # A returned penny comes back; only a settled one is spent (fees not modelled).
        "penny_cost_mxn": cfg["penny_drop"]["amount_mxn"] if p.status == "settled" else 0.0,
        "lookups": 0,
    }
    if p.status != "settled":
        if p.retries_exhausted:
            return {
                **row,
                "decision": HOLD,
                "check": "penny_retries_exhausted",
                "next_action": _action("penny_retries_exhausted", cfg),
            }
        return {
            **row,
            "decision": BLOCK,
            "check": "penny_returned",
            "next_action": _action("penny_returned", cfg),
        }

    row.update(cep_tracking_key=p.cep.tracking_key, cep_rfc=p.cep.beneficiary_rfc)
    if normalize_rfc(p.cep.beneficiary_rfc) != rfc:
        return {
            **row,
            "decision": BLOCK,
            "check": "wrong_owner",
            "next_action": _action("wrong_owner", cfg),
        }

    if lookup is not None and cfg["ownership_lookup"]["enabled"]:
        res = _run_lookup(lookup, clabe, rfc, external_id, p.resolved_at)
        row["lookups"] = 1
        if isinstance(res, str):
            row["lookup_outcome"] = res
        else:
            row["lookup_outcome"] = res.outcome.value
            if res.completed_at is not None:
                row["lookup_minutes"] = (res.completed_at - res.submitted_at).total_seconds() / 60
            if res.outcome == Outcome.UNMATCHED:
                return {
                    **row,
                    "decision": HOLD,
                    "check": "signals_disagree",
                    "next_action": _action("signals_disagree", cfg),
                }
    return {
        **row,
        "decision": VERIFIED,
        "check": "penny_and_rfc_match",
        "verified_at": p.resolved_at,
    }


def verification_summary(results: pd.DataFrame) -> dict:
    new = results[
        results["check"].isin(
            [
                "penny_returned",
                "penny_retries_exhausted",
                "wrong_owner",
                "signals_disagree",
                "penny_and_rfc_match",
            ]
        )
    ]
    penny_s = pd.to_numeric(new["penny_seconds"], errors="coerce").dropna()
    return {
        "payments": len(results),
        "verified": int((results["decision"] == VERIFIED).sum()),
        "blocked": int((results["decision"] == BLOCK).sum()),
        "held": int((results["decision"] == HOLD).sum()),
        "accounts_checked": len(new),
        "reused": int((results["check"] == "reused").sum()),
        "penny_returned": int((new["check"] == "penny_returned").sum()),
        "wrong_owner": int((new["check"] == "wrong_owner").sum()),
        "penny_cost_mxn": round(float(results["penny_cost_mxn"].sum()), 2),
        "previously_blocked": int((results["check"] == "previously_blocked").sum()),
        "lookups": int(results["lookups"].sum()),
        "median_penny_seconds": round(float(penny_s.median()), 1) if len(penny_s) else None,
    }

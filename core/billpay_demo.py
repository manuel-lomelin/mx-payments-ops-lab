"""Glue for the BillPay demo: filter 1 -> filter 2 -> simulated SPEI run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.account_verification import (
    OwnershipLookup,
    SimulatedOwnershipLookup,
    SimulatedPennyDrop,
    VerificationCache,
    load_registry,
    verify_accounts,
)
from core.payments import preflight, read_payments_csv, to_instructions
from core.retry import RetryPolicy
from core.sample_data import generate_bank_registry
from core.spei_sim import BatchResult, SimConfig, run_batch

DATA = Path(__file__).resolve().parent.parent / "data"
SAMPLE_PAYMENTS = DATA / "sample_payments.csv"
SAMPLE_REGISTRY = DATA / "sample_bank_registry.csv"
# Monday 09:00: inside the lookup provider's business-day response window.
DEMO_START = datetime(2026, 3, 2, 9, 0)


def registry_for(df: pd.DataFrame, is_sample: bool) -> dict:
    """The sample file ships with its registry; any other file gets a synthetic one."""
    if is_sample:
        return load_registry(pd.read_csv(SAMPLE_REGISTRY, dtype=str))
    if "beneficiary_rfc" not in df.columns:
        df = df.assign(beneficiary_rfc="")
    return load_registry(generate_bank_registry(df))


@dataclass
class DemoRun:
    report: pd.DataFrame
    verification: pd.DataFrame | None
    batch: BatchResult


def run_pipeline(
    report: pd.DataFrame,
    registry: dict,
    verify: bool = True,
    lookup: OwnershipLookup | None = None,
    cache: VerificationCache | None = None,
    sim: SimConfig | None = None,
    policy: RetryPolicy | None = None,
    seed: int = 7,
    at: datetime = DEMO_START,
) -> DemoRun:
    verification = None
    if verify:
        lookup = lookup or SimulatedOwnershipLookup(registry)
        verification = verify_accounts(report, SimulatedPennyDrop(registry), at, lookup, cache)
    batch = run_batch(
        to_instructions(report, verification), cfg=sim, policy=policy, seed=seed, start=at
    )
    return DemoRun(report, verification, batch)


def sample_run(verify: bool = True) -> DemoRun:
    df = read_payments_csv(SAMPLE_PAYMENTS)
    return run_pipeline(preflight(df), registry_for(df, is_sample=True), verify=verify)

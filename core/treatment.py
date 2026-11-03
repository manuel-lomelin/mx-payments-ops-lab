"""Rules-based treatment strategy, configured in config/treatment.yaml."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.config import load_config


@dataclass(frozen=True)
class Treatment:
    stage: str
    channel: str
    max_contacts_per_week: int
    rule: str


def _matches(rule: dict, row: dict) -> bool:
    if "buckets" in rule and row["dpd_bucket"] not in rule["buckets"]:
        return False
    if "segments" in rule and row.get("segment") not in rule["segments"]:
        return False
    if "min_score" in rule and row.get("risk_score", 0) < rule["min_score"]:
        return False
    if "max_score" in rule and row.get("risk_score", 0) > rule["max_score"]:
        return False
    return not ("min_broken_ptp" in rule and row.get("broken_ptp_6m", 0) < rule["min_broken_ptp"])


def assign(row: dict, cfg: dict | None = None) -> Treatment:
    cfg = cfg or load_config("treatment")
    if row.get("status") == "charged_off":
        stage = cfg["stages"]["agency_handoff"]
        return Treatment(
            "agency_handoff",
            stage["channel"],
            stage["max_contacts_per_week"],
            "charged-off accounts are handled by an agency",
        )
    for rule in cfg["rules"]:
        if _matches(rule, row):
            stage = cfg["stages"][rule["stage"]]
            return Treatment(
                rule["stage"], stage["channel"], stage["max_contacts_per_week"], rule["name"]
            )
    stage = cfg["stages"]["no_action"]
    return Treatment("no_action", stage["channel"], stage["max_contacts_per_week"], "no rule")


def assign_all(scored: pd.DataFrame, accounts: pd.DataFrame) -> pd.DataFrame:
    cfg = load_config("treatment")
    df = scored.merge(accounts, on="account_id", how="left")
    treatments = [assign(r, cfg) for r in df.to_dict("records")]
    df["stage"] = [t.stage for t in treatments]
    df["channel"] = [t.channel for t in treatments]
    df["max_contacts_per_week"] = [t.max_contacts_per_week for t in treatments]
    df["rule"] = [t.rule for t in treatments]
    df["stage_order"] = df["stage"].map({k: v["order"] for k, v in cfg["stages"].items()})
    return df

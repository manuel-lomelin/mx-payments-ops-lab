"""BillPay dashboard metrics, computed in DuckDB from the SQL files in /sql."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.db import connect, query
from core.recon import ReconResult
from core.spei_sim import BatchResult


@dataclass
class BillPayMetrics:
    kpis: dict
    returns_by_reason: pd.DataFrame
    time_to_resolve: pd.DataFrame


def compute_metrics(run: BatchResult, recon: ReconResult | None = None) -> BillPayMetrics:
    con = connect()
    kpis = query(con, "billpay_kpis", payments=run.payments, attempts=run.attempts)
    kpi_row = {k: (None if pd.isna(v) else v) for k, v in kpis.iloc[0].to_dict().items()}
    kpi_row["payments"] = int(kpi_row["payments"])
    kpi_row["return_rate_per_attempt"] = (
        float((run.attempts["status"] == "returned").mean()) if len(run.attempts) else 0.0
    )
    if recon is not None:
        kpi_row["recon_error_rate"] = recon.summary["recon_error_rate"]
    return BillPayMetrics(
        kpis=kpi_row,
        returns_by_reason=query(con, "billpay_returns_by_reason"),
        time_to_resolve=query(con, "billpay_time_to_resolve"),
    )

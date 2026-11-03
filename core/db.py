"""DuckDB helpers. Analytics live as plain .sql files in /sql and run against DataFrames."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def connect(path: str = ":memory:") -> duckdb.DuckDBPyConnection:
    return duckdb.connect(path)


def load_sql(name: str) -> str:
    return (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")


def register(con: duckdb.DuckDBPyConnection, **tables: pd.DataFrame) -> None:
    for table, df in tables.items():
        con.register(table, df)


def query(con: duckdb.DuckDBPyConnection, name: str, **tables: pd.DataFrame) -> pd.DataFrame:
    """Register any given DataFrames as views, then run /sql/<name>.sql."""
    register(con, **tables)
    return con.execute(load_sql(name)).df()

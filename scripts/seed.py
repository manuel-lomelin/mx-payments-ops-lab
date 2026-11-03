"""Write seeded synthetic data to /data. Re-running produces identical output.

- data/sample_payments.csv: supplier payment file for the BillPay module (committed)
- data/lab.duckdb: collections portfolio tables for ad-hoc SQL (git-ignored)
"""

from pathlib import Path

import duckdb

from core.portfolio import generate_portfolio
from core.sample_data import generate_payment_batch

DATA = Path(__file__).resolve().parent.parent / "data"


def main() -> None:
    path = DATA / "sample_payments.csv"
    generate_payment_batch().to_csv(path, index=False)
    print(f"wrote {path}")

    db_path = DATA / "lab.duckdb"
    db_path.unlink(missing_ok=True)
    portfolio = generate_portfolio()
    with duckdb.connect(str(db_path)) as con:
        for name, df in portfolio.tables().items():
            con.register("df", df)
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM df")
            con.unregister("df")
    print(f"wrote {db_path} (try: duckdb data/lab.duckdb < sql/roll_rates.sql)")


if __name__ == "__main__":
    main()

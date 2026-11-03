"""Write seeded synthetic data files to /data. Re-running produces identical output."""

from pathlib import Path

from core.sample_data import generate_payment_batch

DATA = Path(__file__).resolve().parent.parent / "data"


def main() -> None:
    path = DATA / "sample_payments.csv"
    generate_payment_batch().to_csv(path, index=False)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()

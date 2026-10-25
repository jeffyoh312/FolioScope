"""CLI for scheduled snapshots. Example: python scripts/save_snapshot.py --demo"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from portfolio.analytics import calculate_report  # noqa: E402
from portfolio.ledger import build_positions, parse_transactions  # noqa: E402
from portfolio.market import simulated_prices, yahoo_prices  # noqa: E402
from portfolio.snapshots import save_snapshot  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture a dated portfolio-value snapshot in SQLite"
    )
    parser.add_argument(
        "--trades", type=Path, default=ROOT / "data" / "sample_transactions.csv"
    )
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "snapshots.db")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use synthetic prices, never live market data",
    )
    args = parser.parse_args()

    trades = parse_transactions(args.trades)
    positions = build_positions(trades)
    symbols = sorted(set(trades["ticker"]))
    start = trades["date"].min().date() - timedelta(days=7)
    prices = (
        simulated_prices(symbols, start, date.today())
        if args.demo
        else yahoo_prices(symbols, start, date.today())
    )
    report = calculate_report(trades, positions, prices)
    mode = "simulated" if args.demo else "yahoo"
    save_snapshot(args.db, report.total_value, mode)
    print(f"Saved {mode} snapshot: ${report.total_value:,.2f} at {report.as_of.date()}")


if __name__ == "__main__":
    main()

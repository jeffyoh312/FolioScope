from io import StringIO

import pandas as pd
import pytest

from portfolio.analytics import calculate_report
from portfolio.ledger import build_positions, parse_transactions
from portfolio.market import simulated_prices
from portfolio.snapshots import read_snapshots, save_snapshot


def test_a_new_deposit_is_not_counted_as_return():
    """Two buys, flat price: market value doubles; return index stays flat."""
    ledger = parse_transactions(
        StringIO(
            "date,ticker,side,quantity,price,fee\n"
            "2026-01-05,AAPL,BUY,1,100,0\n"
            "2026-01-07,AAPL,BUY,1,100,0\n"
        )
    )
    prices = pd.DataFrame(
        {"AAPL": [100, 100, 100, 100]}, index=pd.bdate_range("2026-01-05", periods=4)
    )
    report = calculate_report(ledger, build_positions(ledger), prices)
    assert report.total_value == 200
    assert report.unrealized_pnl == 0
    assert report.value_history.iloc[0] == 100
    assert report.value_history.iloc[-1] == 200
    assert report.return_index.iloc[-1] == pytest.approx(1.0)


def test_price_rise_changes_return_index_without_new_trade():
    ledger = parse_transactions(
        StringIO("date,ticker,side,quantity,price,fee\n2026-01-05,AAPL,BUY,1,100,0\n")
    )
    prices = pd.DataFrame(
        {"AAPL": [100, 110, 121]}, index=pd.bdate_range("2026-01-05", periods=3)
    )
    report = calculate_report(ledger, build_positions(ledger), prices)
    assert report.total_value == 121
    assert report.unrealized_pnl == 21
    assert report.return_index.iloc[-1] == pytest.approx(1.21)
    assert report.max_drawdown == pytest.approx(0)


def test_drawdown_measured_against_initial_investment():
    ledger = parse_transactions(
        StringIO("date,ticker,side,quantity,price,fee\n2026-01-05,AAPL,BUY,1,100,0\n")
    )
    prices = pd.DataFrame(
        {"AAPL": [100, 90, 85]}, index=pd.bdate_range("2026-01-05", periods=3)
    )
    report = calculate_report(ledger, build_positions(ledger), prices)
    assert report.max_drawdown == pytest.approx(-0.15)


def test_simulation_deterministic():
    from datetime import date

    first = simulated_prices(["AAPL", "MSFT"], date(2026, 1, 5), date(2026, 3, 2))
    second = simulated_prices(["MSFT", "AAPL"], date(2026, 1, 5), date(2026, 3, 2))
    pd.testing.assert_frame_equal(first, second)


def test_sqlite_snapshots(tmp_path):
    db = tmp_path / "snapshots.db"
    save_snapshot(db, 1425.5, "simulated", timestamp="2026-01-01T00:00:00+00:00")
    save_snapshot(db, 1500, "yahoo", timestamp="2026-01-02T00:00:00+00:00")
    saved = read_snapshots(db)
    assert len(saved) == 2
    assert saved["value_usd"].tolist() == [1425.5, 1500]

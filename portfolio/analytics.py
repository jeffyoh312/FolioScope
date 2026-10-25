"""Derived values and a close-to-close, flow-neutral return approximation."""

from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pandas as pd

from .ledger import Position


@dataclass
class PortfolioReport:
    holdings: pd.DataFrame
    value_history: pd.Series
    return_index: pd.Series
    total_value: float
    total_basis: float
    unrealized_pnl: float
    realized_pnl: float
    annual_volatility: float | None
    max_drawdown: float | None
    as_of: pd.Timestamp


def calculate_report(
    trades: pd.DataFrame, positions: dict[str, Position], prices: pd.DataFrame
) -> PortfolioReport:
    if prices.empty:
        raise ValueError("Prices are empty.")
    prices = prices.sort_index().ffill()
    if prices.iloc[-1].isna().any():
        raise ValueError("Latest prices are missing for one or more tickers.")
    prices = prices.astype(float)

    daily_qty = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    for _, trade in trades.iterrows():
        ticker = trade["ticker"]
        if ticker not in prices:
            raise ValueError(f"No market prices provided for {ticker}.")
        direction = 1 if trade["side"] == "BUY" else -1
        daily_qty.loc[daily_qty.index >= trade["date"], ticker] += direction * float(
            trade["quantity"]
        )

    # Holdings value is not itself a performance/return curve: trades change it.
    value_history = (daily_qty * prices).sum(axis=1, min_count=1).fillna(0.0)

    # Trades assumed to execute at the close; yesterday's positions earn today's
    # close-to-close movement. Cash, FX, fees, dividends and splits are omitted.
    previous_qty = daily_qty.shift(1)
    previous_value = (previous_qty * prices.shift(1)).sum(axis=1, min_count=1)
    price_profit = (previous_qty * prices.diff()).sum(axis=1, min_count=1)
    daily_return = (
        (price_profit / previous_value.where(previous_value > 0))
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    return_index = (1 + daily_return).cumprod()
    invested_days = value_history[value_history > 0]
    if not invested_days.empty:
        # The initial 100 baseline must be present for drawdown calculations.
        baseline = pd.Series([1.0], index=[invested_days.index[0]])
        return_index = pd.concat(
            [baseline, return_index[return_index.index > baseline.index[0]]]
        )
    if len(daily_return) > 1:
        annual_vol = float(daily_return.std(ddof=1) * np.sqrt(252))
        drawdown = return_index / return_index.cummax() - 1
        max_drawdown = float(drawdown.min())
    else:
        annual_vol = None
        max_drawdown = None

    rows = []
    for ticker, position in positions.items():
        if position.quantity <= Decimal("0"):
            continue
        quantity = float(position.quantity)
        price = float(prices[ticker].iloc[-1])
        basis = float(position.cost_basis)
        market_value = quantity * price
        rows.append(
            {
                "Ticker": ticker,
                "Shares": quantity,
                "Price": price,
                "Market value": market_value,
                "Cost basis": basis,
                "Unrealized P/L": market_value - basis,
                "Return %": (market_value / basis - 1) * 100 if basis else 0,
            }
        )
    holdings = pd.DataFrame(
        rows,
        columns=[
            "Ticker",
            "Shares",
            "Price",
            "Market value",
            "Cost basis",
            "Unrealized P/L",
            "Return %",
        ],
    )
    if not holdings.empty:
        holdings = holdings.sort_values("Market value", ascending=False).reset_index(
            drop=True
        )
        total = float(holdings["Market value"].sum())
        holdings["Weight %"] = holdings["Market value"] / total * 100 if total else 0
    else:
        total = 0.0
        holdings["Weight %"] = pd.Series(dtype=float)

    basis = float(holdings["Cost basis"].sum())
    return PortfolioReport(
        holdings=holdings,
        value_history=value_history,
        return_index=return_index,
        total_value=total,
        total_basis=basis,
        unrealized_pnl=total - basis,
        realized_pnl=float(
            sum((p.realized_pnl for p in positions.values()), Decimal("0"))
        ),
        annual_volatility=annual_vol,
        max_drawdown=max_drawdown,
        as_of=prices.index[-1],
    )

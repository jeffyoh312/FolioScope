"""Market-data adapters; the deterministic demo is expressly not real data."""

from datetime import date, timedelta
from hashlib import sha256

import numpy as np
import pandas as pd

DEMO_START_PRICE = {"AAPL": 240.0, "MSFT": 465.0, "NVDA": 185.0, "VOO": 600.0}


def simulated_prices(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    days = pd.bdate_range(start, end)
    if days.empty:
        raise ValueError("No market dates are available in this date range.")
    values = {}
    for ticker in sorted(tickers):
        seed = int.from_bytes(sha256(ticker.encode()).digest()[:4], "big")
        rng = np.random.default_rng(seed)
        returns = rng.normal(0.00025, 0.014, len(days))
        path = np.cumprod(1 + returns)
        values[ticker] = (DEMO_START_PRICE.get(ticker, 110.0) * path).round(2)
    return pd.DataFrame(values, index=days)


def yahoo_prices(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """Fetch daily *unadjusted* closes; require USD to prevent invalid aggregation."""
    import yfinance as yf

    closes = {}
    for symbol in sorted(tickers):
        instrument = yf.Ticker(symbol)
        try:
            currency = instrument.fast_info.get("currency")
            if not currency or currency.upper() != "USD":
                raise ValueError(
                    f"{symbol}: quote currency is {currency or 'unknown'}, not USD."
                )
            frame = instrument.history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                auto_adjust=False,
                actions=False,
            )
            if frame.empty or "Close" not in frame:
                raise ValueError(f"{symbol}: no daily prices returned.")
            close = frame["Close"].copy()
            close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
            closes[symbol] = close.astype(float)
        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Could not fetch {symbol} from Yahoo Finance: {exc}"
            ) from exc

    prices = pd.DataFrame(closes).sort_index().ffill()
    if prices.empty or prices.iloc[-1].isna().any():
        raise ValueError("At least one ticker has no usable price data.")
    return prices

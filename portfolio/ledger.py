"""Validate a trade ledger and calculate open positions using FIFO lots."""

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ("date", "ticker", "side", "quantity", "price", "fee")


@dataclass(frozen=True)
class Position:
    ticker: str
    quantity: Decimal
    cost_basis: Decimal
    realized_pnl: Decimal

    @property
    def average_cost(self) -> Decimal:
        return self.cost_basis / self.quantity if self.quantity else Decimal("0")


def _decimal(
    value: object, field: str, row: int, *, allow_zero: bool = False
) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Row {row}: {field} must be a number.") from None
    if not parsed.is_finite() or parsed < 0 or (parsed == 0 and not allow_zero):
        restriction = "nonnegative" if allow_zero else "positive"
        raise ValueError(f"Row {row}: {field} must be a finite {restriction} number.")
    return parsed


def parse_transactions(source: str | Path | object) -> pd.DataFrame:
    """Parse a CSV from disk or Streamlit without losing decimal precision.

    Excel may save CSV files with a BOM, semicolon separator or extra blank rows.
    Those are formatting differences, not invalid financial transactions.
    """
    try:
        raw = pd.read_csv(
            source,
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
            sep=None,
            engine="python",
            skip_blank_lines=True,
        )
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as error:
        raise ValueError("This does not look like a readable CSV. Download the template and try again.") from error
    raw.columns = [str(name).strip().lower().lstrip("\ufeff") for name in raw.columns]
    raw = raw.loc[~raw.apply(lambda row: all(not str(value).strip() for value in row), axis=1)].copy()
    missing = sorted(set(REQUIRED_COLUMNS) - set(raw.columns))
    if missing:
        raise ValueError(
            f"Missing CSV columns: {', '.join(missing)}. "
            "Required headers: date, ticker, side, quantity, price, fee."
        )
    if raw.empty:
        raise ValueError("The CSV contains no transactions.")

    records = []
    for index, row in raw.iterrows():
        number = index + 2
        try:
            date_string = str(row["date"]).strip()
            if date_string.endswith(" 00:00:00"):
                date_string = date_string.split(" ")[0]
            date_string = date_string.replace("/", "-")
            date = pd.to_datetime(date_string, format="%Y-%m-%d", exact=True, errors="raise")
        except (ValueError, TypeError):
            raise ValueError(
                f"Row {number}: date must be YYYY-MM-DD (e.g. 2026-01-05). "
                "If Excel changed the date format, format the column as text and save again."
            ) from None
        if date.normalize() > pd.Timestamp.now().normalize():
            raise ValueError(f"Row {number}: future-dated trades are not supported.")
        ticker = str(row["ticker"]).strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,15}", ticker):
            raise ValueError(f"Row {number}: invalid ticker '{ticker}'.")
        side = str(row["side"]).strip().upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError(f"Row {number}: side must be BUY or SELL.")
        records.append(
            {
                "date": date.normalize(),
                "ticker": ticker,
                "side": side,
                "quantity": _decimal(row["quantity"], "quantity", number),
                "price": _decimal(row["price"], "price", number),
                "fee": _decimal(row["fee"], "fee", number, allow_zero=True),
                "_order": index,
            }
        )

    return (
        pd.DataFrame(records)
        .sort_values(["date", "_order"], kind="stable")
        .reset_index(drop=True)
    )


def build_positions(trades: pd.DataFrame) -> dict[str, Position]:
    """FIFO accounting, including purchase and sale fees in the relevant P/L."""
    lots: dict[str, deque[list[Decimal]]] = defaultdict(deque)
    realized = defaultdict(lambda: Decimal("0"))
    for index, trade in trades.iterrows():
        ticker = trade["ticker"]
        qty, price, fee = (trade[key] for key in ("quantity", "price", "fee"))
        if trade["side"] == "BUY":
            lots[ticker].append([qty, price + fee / qty])
            continue

        held = sum((lot[0] for lot in lots[ticker]), Decimal("0"))
        if qty > held:
            raise ValueError(
                f"Trade {index + 1}: cannot sell {qty} {ticker}; only {held} held."
            )
        remaining = qty
        sold_cost = Decimal("0")
        while remaining > 0:
            available, unit_cost = lots[ticker][0]
            consumed = min(remaining, available)
            sold_cost += consumed * unit_cost
            remaining -= consumed
            if consumed == available:
                lots[ticker].popleft()
            else:
                lots[ticker][0][0] -= consumed
        realized[ticker] += qty * price - fee - sold_cost

    result = {}
    for ticker in sorted(set(lots) | set(realized)):
        quantity = sum((lot[0] for lot in lots[ticker]), Decimal("0"))
        basis = sum((lot[0] * lot[1] for lot in lots[ticker]), Decimal("0"))
        result[ticker] = Position(ticker, quantity, basis, realized[ticker])
    return result

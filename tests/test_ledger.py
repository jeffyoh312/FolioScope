from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path

import pytest

from portfolio.ledger import build_positions, parse_transactions


def trades(text: str):
    return parse_transactions(StringIO("date,ticker,side,quantity,price,fee\n" + text))


def test_fifo_cost_basis_and_realized_profit():
    data = trades(
        "2026-01-02,AAPL,BUY,2,100,2\n"
        "2026-02-02,AAPL,BUY,1,120,0\n"
        "2026-03-02,AAPL,SELL,2.5,150,1\n"
    )
    result = build_positions(data)["AAPL"]
    assert result.quantity == Decimal("0.5")
    assert result.cost_basis == Decimal("60.0")
    # Sale proceeds: 374; FIFO sold basis: (2 * 101) + (.5 * 120) = 262.
    assert result.realized_pnl == Decimal("112.0")


def test_cannot_sell_more_than_owned():
    with pytest.raises(ValueError, match="cannot sell"):
        build_positions(trades("2026-01-02,VOO,SELL,1,500,0\n"))


@pytest.mark.parametrize(
    "line,match",
    [
        ("2026-01-02,MSFT,BUY,-1,100,0\n", "quantity"),
        ("2026-01-02,MSFT,BUY,1,100,-1\n", "fee"),
        ("2026-01-02,MSFT,HOLD,1,100,0\n", "side"),
        ("02/01/2026,MSFT,BUY,1,100,0\n", "date"),
        ("2026-01-02,MSFT,BUY,1,NaN,0\n", "price"),
    ],
)
def test_invalid_transactions(line, match):
    with pytest.raises(ValueError, match=match):
        trades(line)


def test_shares_exactly_sold_have_zero_basis():
    result = build_positions(
        trades("2026-01-02,NVDA,BUY,3,100,0\n2026-02-03,NVDA,SELL,3,110,0\n")
    )["NVDA"]
    assert result.quantity == 0
    assert result.cost_basis == 0
    assert result.realized_pnl == 30


def test_downloaded_template_can_be_uploaded_unchanged():
    template = Path(__file__).parents[1] / "data" / "sample_transactions.csv"
    uploaded_bytes = BytesIO(template.read_bytes())
    imported = parse_transactions(uploaded_bytes)
    assert len(imported) == 7
    assert set(imported["ticker"]) == {"AAPL", "MSFT", "NVDA", "VOO"}
    assert build_positions(imported)["NVDA"].quantity > 0


def test_excel_semicolon_csv_with_bom_and_spaces():
    content = "\ufeffDate ; Ticker ; Side ; Quantity ; Price ; Fee\n2026/01/05;AAPL;BUY;2;150;0\n\n"
    imported = parse_transactions(BytesIO(content.encode("utf-8")))
    assert len(imported) == 1
    assert imported.iloc[0]["ticker"] == "AAPL"

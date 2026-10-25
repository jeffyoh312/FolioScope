"""Test Groq integration without making network requests or spending API credits."""

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from portfolio.analytics import calculate_report
from portfolio.insights import (
    build_prompt,
    extract_answer_links,
    generate_ai_commentary,
)
from portfolio.ledger import build_positions, parse_transactions
from portfolio.market import simulated_prices


def example_report():
    sample = Path(__file__).parents[1] / "data" / "sample_transactions.csv"
    trades = parse_transactions(sample)
    positions = build_positions(trades)
    prices = simulated_prices(
        sorted(trades["ticker"].unique()), date(2025, 12, 29), date(2026, 10, 23)
    )
    return calculate_report(trades, positions, prices)


def test_extracts_existing_https_links_without_inventing_sources():
    answer = (
        "See [official release](https://www.sec.gov/Archives/filing) and "
        "https://example.com/article. Avoid [unsafe](javascript:alert(1)) or "
        "http://example.org/no-tls."
    )
    sources = extract_answer_links(answer)
    assert {source.url for source in sources} == {
        "https://www.sec.gov/Archives/filing",
        "https://example.com/article",
    }
    assert extract_answer_links("News might matter, but I have no link.") == ()


def test_prompt_does_not_send_raw_transaction_history():
    prompt = build_prompt(example_report(), "AAPL", simulated=True, web=True)
    assert "SIMULATED" in prompt
    assert "2026-01-05" not in prompt  # transaction dates are not transmitted
    assert '"currency": "USD"' in prompt
    assert "HTTPS" in prompt


def test_groq_called_only_on_request_and_search_is_optional(monkeypatch):
    calls = []

    class StubGroq:
        def __init__(self, *, api_key, timeout):
            assert api_key == "dummy-key"
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=(
                    "Risk is concentrated. [Issuer](https://example.com/report)"
                )))]
            )

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "groq", SimpleNamespace(Groq=StubGroq))
    report = example_report()

    without_news = generate_ai_commentary(
        report, "dummy-key", focus_ticker="AAPL", simulated=True,
        search_recent_sources=False,
    )
    assert without_news.sources == ()
    assert "tools" not in calls[-1]
    assert calls[-1]["model"] == "openai/gpt-oss-20b"

    with_news = generate_ai_commentary(
        report, "dummy-key", focus_ticker="AAPL", simulated=False,
        search_recent_sources=True,
    )
    assert with_news.sources[0].url == "https://example.com/report"
    assert calls[-1]["tools"] == [{"type": "browser_search"}]
    assert calls[-1]["tool_choice"] == "required"

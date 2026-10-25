"""FolioScope's Streamlit interface.

All financial calculations live in portfolio/. This file handles user input,
navigation, and the presentation of those calculated results.
"""

from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from portfolio.analytics import calculate_report
from portfolio.insights import (
    configured_api_key,
    generate_ai_commentary,
    rules_based_insights,
)
from portfolio.ledger import build_positions, parse_transactions
from portfolio.market import simulated_prices, yahoo_prices
from portfolio.snapshots import read_snapshots

ROOT = Path(__file__).parent
SAMPLE_FILE = ROOT / "data" / "sample_transactions.csv"
SNAPSHOT_FILE = ROOT / "data" / "snapshots.db"
LOGO_FILE = ROOT / "assets" / "folioscope-logo.png"
FAVICON_FILE = ROOT / "assets" / "folioscope-favicon.png"

st.set_page_config(
    page_title="FolioScope",
    page_icon=str(FAVICON_FILE) if FAVICON_FILE.is_file() else "📊",
    layout="wide",
)


def display_header() -> None:
    """Use the user's logo when supplied, with a readable text fallback."""
    if LOGO_FILE.is_file():
        st.image(str(LOGO_FILE), width=310, alt="FolioScope")
    else:
        st.title("FolioScope")
    st.write(
        "See what you own, how much it is worth, and how your investments "
        "have changed."
    )


def format_money(value: float) -> str:
    return f"${value:,.2f}"


def chart_style(fig: go.Figure, height: int = 330) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=15, r=15, t=15, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#253246"),
        xaxis=dict(showgrid=False),
        yaxis=dict(gridcolor="#e7ebf0"),
    )
    return fig


def current_signature(report, simulated: bool, ticker: str, use_web: bool) -> tuple:
    """Prevent an old AI answer appearing after the user changes inputs."""
    weights = tuple(
        (row["Ticker"], round(float(row["Weight %"]), 5))
        for row in report.holdings.to_dict("records")
    )
    return (
        simulated,
        report.as_of.isoformat(),
        round(report.total_value, 4),
        round(report.realized_pnl, 4),
        weights,
        ticker,
        use_web,
    )


@st.cache_data(ttl=900, show_spinner=False)
def cached_prices(
    symbols: tuple[str, ...], start: date, end: date, simulated: bool
) -> pd.DataFrame:
    """Avoid downloading identical quotes after every widget interaction."""
    if simulated:
        return simulated_prices(list(symbols), start, end)
    return yahoo_prices(list(symbols), start, end)


display_header()
st.divider()

with st.sidebar:
    st.header("Your portfolio")
    st.markdown("**1. Choose your transactions**")
    data_choice = st.radio(
        "Transaction source",
        ("Use example transactions", "Upload my CSV"),
        label_visibility="collapsed",
    )
    uploaded_file = None
    if data_choice == "Upload my CSV":
        uploaded_file = st.file_uploader(
            "Select a CSV file",
            type="csv",
            help="A table of buys and sells, not a brokerage login or PDF statement.",
        )
        st.caption("Required: date, ticker, side, quantity, price, fee.")

    st.download_button(
        "Download example CSV",
        data=SAMPLE_FILE.read_bytes(),
        file_name="folioscope_example_transactions.csv",
        mime="text/csv",
        width="stretch",
    )

    st.markdown("**2. Choose where prices come from**")
    price_choice = st.radio(
        "Market prices",
        ("Simulated example prices", "Yahoo Finance closing prices"),
        label_visibility="collapsed",
    )
    simulated = price_choice == "Simulated example prices"
    if simulated:
        st.caption("The prices are fictional. Use this mode to explore the app.")
    else:
        st.caption("Uses recent USD closing prices. An internet connection is required.")

    st.divider()
    st.caption("No brokerage account connection. USD transactions only.")

if data_choice == "Upload my CSV" and uploaded_file is None:
    st.info("Choose a CSV in the sidebar, or select 'Use example transactions' to explore the app.")
    st.stop()

try:
    source = BytesIO(uploaded_file.getvalue()) if uploaded_file is not None else SAMPLE_FILE
    transactions = parse_transactions(source)
    positions = build_positions(transactions)
    tickers = sorted(set(transactions["ticker"]))
    if len(tickers) > 12:
        raise ValueError("This version supports up to 12 different stock symbols.")
except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as error:
    st.error(f"Could not import the CSV: {error}")
    with st.expander("Check the CSV format", expanded=True):
        st.write(
            "Download the example CSV and keep these column headings exactly: "
            "date, ticker, side, quantity, price, fee."
        )
        st.code(
            "date,ticker,side,quantity,price,fee\n"
            "2026-01-05,AAPL,BUY,2,200,1",
            language="csv",
        )
        st.caption(
            "Dates should use YYYY-MM-DD. If Excel changed them to DD/MM/YYYY, "
            "format that column as text and save the file as CSV UTF-8."
        )
    st.stop()


@st.fragment(run_every="15m")
def render_portfolio() -> None:
    """Refresh market data while the browser session stays open."""
    try:
        start = transactions["date"].min().date() - timedelta(days=7)
        prices = cached_prices(tuple(tickers), start, date.today(), simulated)
        report = calculate_report(transactions, positions, prices)
    except Exception as error:
        st.error(f"Could not load the portfolio: {error}")
        st.info(
            "If Yahoo Finance is unavailable, choose 'Simulated example prices' "
            "in the sidebar. Your CSV will stay selected."
        )
        return

    source_label = "simulated prices" if simulated else "Yahoo Finance closing prices"
    st.caption(
        f"{len(transactions)} transactions • {len(tickers)} symbols • "
        f"Prices dated {report.as_of:%d %b %Y} ({source_label})"
    )
    if uploaded_file is not None and simulated:
        st.warning(
            "You uploaded real transactions but selected simulated prices. "
            "The displayed market values and gains are only examples."
        )
    if not simulated and (date.today() - report.as_of.date()).days > 5:
        st.warning("The latest quote is older than five days. Check the data before relying on it.")

    summary, holdings_tab, performance_tab, ai_tab, help_tab = st.tabs(
        ["Summary", "Holdings & trades", "Performance & risk", "AI explanation", "Data & help"]
    )

    with summary:
        st.subheader("Your portfolio at a glance")
        st.caption("These numbers use the latest available closing prices.")
        metric_columns = st.columns(4)
        metric_columns[0].metric(
            "Current value", format_money(report.total_value),
            help="Market value of the shares still held, not your deposits or profit.",
        )
        metric_columns[1].metric(
            "Profit / loss on open shares",
            f"${report.unrealized_pnl:+,.2f}",
            help="Current market value minus the purchase cost of shares still held.",
        )
        metric_columns[2].metric(
            "Profit / loss from sales",
            f"${report.realized_pnl:+,.2f}",
            help="Profit or loss from completed sales, using FIFO purchase costs.",
        )
        metric_columns[3].metric(
            "Stocks currently held",
            len(report.holdings),
            help="Number of symbols with an open position.",
        )

        left, right = st.columns([1.6, 1], gap="large")
        with left:
            st.markdown("#### Value of your holdings over time")
            st.caption("Buying more shares can increase this chart even if prices stay flat.")
            value_fig = go.Figure()
            value_fig.add_trace(
                go.Scatter(
                    x=report.value_history.index,
                    y=report.value_history.values,
                    mode="lines",
                    line=dict(color="#0b806f", width=3),
                    hovertemplate="%{x|%d %b %Y}<br>$%{y:,.2f}<extra></extra>",
                )
            )
            value_fig.update_yaxes(tickprefix="$", tickformat=",.0f")
            st.plotly_chart(chart_style(value_fig), width="stretch", config={"displayModeBar": False})
        with right:
            st.markdown("#### Where your money is allocated")
            st.caption("How much of your current holdings is in each stock.")
            if report.holdings.empty:
                st.info("No shares are currently held.")
            else:
                allocation_fig = px.pie(
                    report.holdings,
                    names="Ticker",
                    values="Market value",
                    hole=0.58,
                    color_discrete_sequence=["#0b806f", "#3672a9", "#9b79ca", "#cf9d46", "#be667f"],
                )
                allocation_fig.update_traces(textinfo="percent")
                st.plotly_chart(
                    chart_style(allocation_fig), width="stretch", config={"displayModeBar": False}
                )

        with st.expander("What is the difference between value and profit?"):
            st.write(
                "Portfolio value is what your current shares are worth. "
                "Unrealized profit/loss compares that value with what those remaining shares cost. "
                "Realized profit/loss comes from shares you already sold."
            )

    with holdings_tab:
        st.subheader("Shares you currently own")
        if report.holdings.empty:
            st.info("There are no open holdings in your CSV.")
        else:
            st.dataframe(
                report.holdings,
                width="stretch",
                hide_index=True,
                column_config={
                    "Shares": st.column_config.NumberColumn(format="%.4f"),
                    "Price": st.column_config.NumberColumn(format="$%.2f"),
                    "Market value": st.column_config.NumberColumn(format="$%.2f"),
                    "Cost basis": st.column_config.NumberColumn(format="$%.2f"),
                    "Unrealized P/L": st.column_config.NumberColumn(format="$%.2f"),
                    "Return %": st.column_config.NumberColumn(format="%.2f%%"),
                    "Weight %": st.column_config.ProgressColumn(
                        min_value=0, max_value=100, format="%.1f%%"
                    ),
                },
            )
        st.download_button(
            "Download holdings as CSV",
            data=report.holdings.to_csv(index=False),
            file_name="folioscope_holdings.csv",
            mime="text/csv",
        )
        st.markdown("#### Transactions imported")
        st.write("This is what FolioScope read from your CSV.")
        st.dataframe(
            transactions.drop(columns="_order").astype(str),
            width="stretch",
            hide_index=True,
        )

    with performance_tab:
        st.subheader("Price-based performance")
        st.caption(
            "This estimates how the prices of shares you held changed. "
            "It does not treat new purchases as investment gains."
        )
        if report.return_index.empty:
            st.info("Not enough price history is available to calculate an index.")
        else:
            index_fig = go.Figure()
            index_fig.add_trace(
                go.Scatter(
                    x=report.return_index.index,
                    y=report.return_index.values * 100,
                    mode="lines",
                    line=dict(color="#3672a9", width=3),
                    hovertemplate="%{x|%d %b %Y}<br>Index: %{y:.2f}<extra></extra>",
                )
            )
            st.plotly_chart(chart_style(index_fig), width="stretch", config={"displayModeBar": False})
        st.caption("The index begins at 100. It is an approximation, not a broker-verified return.")
        a, b = st.columns(2)
        a.metric(
            "Historical volatility",
            f"{report.annual_volatility:.1%}" if report.annual_volatility is not None else "Not enough data",
            help="How much modeled daily returns fluctuated, scaled to a typical trading year.",
        )
        b.metric(
            "Largest modeled decline",
            f"{report.max_drawdown:.1%}" if report.max_drawdown is not None else "Not enough data",
            help="The greatest fall from a prior high in the modeled return index.",
        )
        st.info(
            "These calculations exclude cash, dividends, tax, foreign-exchange effects, "
            "stock splits and some trading costs. They should not be used for investment decisions."
        )

    with ai_tab:
        st.subheader("Explain my portfolio")
        st.write(
            "The observations below come from the calculated numbers. "
            "You do not need an API key to read them."
        )
        for observation in rules_based_insights(report):
            st.markdown(f"- {observation}")

        st.divider()
        st.markdown("#### Ask Groq for an explanation")
        st.caption(
            "Optional. Groq receives a summary of your holdings and metrics, not the uploaded CSV."
        )
        focus = st.selectbox("Focus on", tickers)
        entered_key = st.text_input(
            "Groq API key",
            type="password",
            help="Create one at console.groq.com. Never put it in a file you commit to GitHub.",
        )
        # A server environment key must never be prefilled into a browser field.
        # Even a masked password box exposes its value to the browser session.
        key = entered_key.strip() or configured_api_key()
        if not entered_key and configured_api_key():
            st.caption("A server-side Groq key is configured; it is not shown here.")
        search_web = st.checkbox(
            "Include recent articles and public sources",
            value=False,
            help="Allows Groq to perform browser searches. This can use quota or paid credits.",
        )
        if simulated and search_web:
            st.warning(
                "Your prices are fictional. Real news must not be used to explain the simulated changes."
            )
        if st.button("Explain portfolio", type="primary", disabled=not bool(key.strip())):
            with st.spinner("Asking Groq..."):
                try:
                    explanation = generate_ai_commentary(
                        report,
                        key,
                        focus_ticker=focus,
                        simulated=simulated,
                        search_recent_sources=search_web,
                    )
                    st.session_state["ai_explanation"] = explanation
                    st.session_state["ai_signature"] = current_signature(
                        report, simulated, focus, search_web
                    )
                except Exception as error:
                    st.error(f"Could not generate an explanation: {error}")

        signature = current_signature(report, simulated, focus, search_web)
        if st.session_state.get("ai_signature") == signature:
            explanation = st.session_state["ai_explanation"]
            st.markdown(explanation.text)
            if explanation.web_requested:
                st.markdown("#### Links mentioned in the answer")
                if explanation.sources:
                    for source in explanation.sources:
                        st.link_button(source.title, source.url)
                    st.caption(
                        "These links were included in Groq's response. "
                        "FolioScope has not independently checked the articles."
                    )
                else:
                    st.warning(
                        "Groq did not return usable article links. Treat current-events "
                        "claims as unverified."
                    )
        elif not key:
            st.caption("Enter a key to generate an optional Groq explanation.")
        st.caption("AI-generated commentary is not financial advice or a price forecast.")

    with help_tab:
        st.subheader("What should I upload?")
        st.write(
            "A CSV spreadsheet with one row for every stock purchase or sale. "
            "You can download a working example from the sidebar."
        )
        st.code(
            "date,ticker,side,quantity,price,fee\n"
            "2026-01-05,AAPL,BUY,4,245,1\n"
            "2026-04-02,AAPL,BUY,2,260,1\n"
            "2026-06-15,AAPL,SELL,3,270,1",
            language="csv",
        )
        st.write(
            "Use dates like 2026-01-05, stock symbols like AAPL, BUY or SELL, "
            "a positive number of shares and a price in USD. Fees can be zero."
        )
        st.markdown("#### Saved value snapshots")
        snapshots = read_snapshots(SNAPSHOT_FILE)
        if snapshots.empty:
            st.caption(
                "No snapshots have been saved yet. A separate command-line script can record "
                "a value in the local SQLite database on a schedule."
            )
        else:
            st.dataframe(snapshots.tail(15), width="stretch", hide_index=True)
        st.markdown("#### Data limitations")
        st.write(
            "FolioScope is a personal learning project. It has no brokerage connection, "
            "does not hold money, and does not calculate dividends, taxes, stock splits, "
            "cash balances or foreign-currency conversions."
        )


render_portfolio()

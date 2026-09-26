from __future__ import annotations

import html
from io import BytesIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf

from screener import DOWNLOAD_TIMEOUT_SECONDS, PERIOD, tradingview_ema, ticker_symbol


ROOT = Path(__file__).resolve().parent
DATASETS = {
    "Pattern matches": ROOT / "pattern_charts" / "pattern_matches.csv",
    "All screener matches": ROOT / "screened_charts" / "matches.csv",
}
chart_keyboard = components.declare_component(
    "chart_keyboard",
    path=str(ROOT / "components" / "chart_keyboard"),
)

st.set_page_config(
    page_title="Stock Review | NSE Screener",
    page_icon="ðŸ“ˆ",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { --bg: #0c0f14; --panel: #14181f; --line: #282e38; --text: #d1d4dc; --muted: #89909e; --blue: #2962ff; }
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] { background: var(--bg); color: var(--text); }
    .block-container { padding: 0.8rem 1rem 1.2rem; max-width: 1900px; }
    h1, h2, h3, p { color: var(--text); }
    h1 { font-size: 1.25rem !important; margin: 0 !important; }
    h2, h3 { font-size: 1rem !important; }
    [data-testid="stMetric"] { background: transparent; border: 0; border-right: 1px solid var(--line); padding: 0.2rem 0.7rem; }
    [data-testid="stMetricLabel"] { color: var(--muted); }
    [data-testid="stMetricValue"] { font-size: 1rem; }
    [data-testid="stSidebar"] { background: var(--panel); }
    [data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 3px; }
    [data-testid="stTextInput"] input, [data-testid="stSelectbox"] [data-baseweb="select"] > div { background: var(--panel); }
    .topline { min-height: 2.4rem; display: flex; align-items: center; gap: 1rem; border-bottom: 1px solid var(--line); margin-bottom: 0.75rem; }
    .brand { font-size: 0.9rem; font-weight: 700; color: var(--text); }
    .exchange { color: var(--muted); font-size: 0.82rem; }
    .chartbar { display: flex; justify-content: space-between; align-items: baseline; border-bottom: 1px solid var(--line); padding: 0.55rem 0; margin-bottom: 0.25rem; }
    .chartbar strong { font-size: 1.2rem; }
    .watchlist-title { display: flex; justify-content: space-between; align-items: baseline; border-bottom: 1px solid var(--line); padding-bottom: 0.45rem; }
    .watchlist-title strong { font-size: 1rem; }
    .watchlist-count { color: var(--muted); font-size: 0.76rem; }
    .hint { color: var(--muted); font-size: 0.75rem; }
    [data-testid="stDataFrame"] * { font-size: 0.82rem; }
    @media (max-width: 900px) { .block-container { padding: 0.5rem; } }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def load_results(csv_path: str, file_version: int) -> pd.DataFrame:
    """Load results and invalidate the cache whenever the CSV is replaced."""
    frame = pd.read_csv(csv_path)
    if "symbol" not in frame.columns:
        raise ValueError("The results CSV must contain a 'symbol' column.")
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame = frame[frame["symbol"].ne("")].drop_duplicates("symbol")
    for column in (
        "price_inr",
        "return_60d_pct",
        "return_3m",
        "consolidation_range_pct",
    ):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


@st.cache_data(ttl=3600, show_spinner=False)
def load_chart_prices(symbol: str) -> pd.DataFrame:
    prices = yf.download(
        ticker_symbol(symbol),
        period=PERIOD,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )
    if prices.empty:
        return prices
    if isinstance(prices.columns, pd.MultiIndex):
        prices.columns = prices.columns.get_level_values(0)
    prices = prices.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    for period in (20, 50, 200):
        prices[f"EMA{period}"] = tradingview_ema(prices["Close"], period)
    return prices.tail(180)


@st.cache_data(ttl=3600, max_entries=300, show_spinner=False)
def render_chart(symbol: str) -> bytes:
    """Render a chart once per symbol and reuse the PNG across reruns."""
    chart_prices = load_chart_prices(symbol)
    if chart_prices.empty:
        return b""

    addplots = [
        mpf.make_addplot(chart_prices[f"EMA{period}"], color=color, width=1)
        for period, color in ((20, "#f59e0b"), (50, "#2962ff"), (200, "#e83e8c"))
    ]
    figure, _ = mpf.plot(
        chart_prices,
        type="candle",
        style="nightclouds",
        volume=True,
        addplot=addplots,
        title=f"{symbol} | Daily | NSE",
        figsize=(14, 8),
        returnfig=True,
    )
    image = BytesIO()
    figure.savefig(image, format="png", dpi=120, bbox_inches="tight")
    plt.close(figure)
    return image.getvalue()


def display_value(row: pd.Series, column: str, suffix: str = "") -> str:
    value = row.get(column)
    if pd.isna(value):
        return "â€”"
    return f"{float(value):,.2f}{suffix}"


def move_selection(symbols: list[str], offset: int) -> None:
    current_index = symbols.index(st.session_state["review_symbol"])
    target_index = min(max(current_index + offset, 0), len(symbols) - 1)
    st.session_state["review_symbol"] = symbols[target_index]


st.markdown(
    '<div class="topline"><span class="brand">NSE Â· CHART REVIEW</span>'
    '<span class="exchange">Daily charts Â· Screener workspace</span></div>',
    unsafe_allow_html=True,
)

chart_column, watchlist_column = st.columns([3.2, 1.05], gap="small")

with watchlist_column:
    st.markdown(
        '<div class="watchlist-title"><strong>Watchlist</strong>'
        '<span class="watchlist-count">NSE</span></div>',
        unsafe_allow_html=True,
    )
    dataset_name = st.selectbox("Stock set", list(DATASETS), label_visibility="collapsed")
    csv_path = DATASETS[dataset_name]
    search = st.text_input("Find symbol", placeholder="Search symbols", label_visibility="collapsed").strip().upper()
    sort_label = st.selectbox(
        "Sort watchlist",
        ["Symbol (A to Z)", "Price (high to low)", "Return (high to low)"],
        label_visibility="collapsed",
    )

if not csv_path.exists():
    st.error(f"Results file not found: {csv_path.relative_to(ROOT)}")
    st.info("Run the relevant screener script first, then refresh this page.")
    st.stop()

try:
    results = load_results(str(csv_path), csv_path.stat().st_mtime_ns)
except (OSError, ValueError, pd.errors.ParserError) as error:
    st.error(f"Could not load the results: {error}")
    st.stop()

if search:
    results = results[results["symbol"].str.contains(search, regex=False)]

return_column = "return_60d_pct" if "return_60d_pct" in results.columns else "return_3m"
if return_column in results.columns:
    results["review_return_pct"] = pd.to_numeric(results[return_column], errors="coerce")
    if return_column == "return_3m":
        results["review_return_pct"] *= 100
if sort_label == "Price (high to low)" and "price_inr" in results.columns:
    results = results.sort_values("price_inr", ascending=False, na_position="last")
elif sort_label == "Return (high to low)" and "review_return_pct" in results.columns:
    results = results.sort_values("review_return_pct", ascending=False, na_position="last")
else:
    results = results.sort_values("symbol")

if results.empty:
    st.warning("No symbols match that search.")
    st.stop()

symbols = results["symbol"].tolist()
if st.session_state.get("dataset_name") != dataset_name:
    st.session_state["dataset_name"] = dataset_name
    st.session_state.pop("review_symbol", None)
if st.session_state.get("review_symbol") not in symbols:
    st.session_state["review_symbol"] = symbols[0]

selected_row = results.loc[results["symbol"].eq(st.session_state["review_symbol"])].iloc[0]
latest_date = selected_row.get("latest_data_date", "")
table_columns = [column for column in ("symbol", "price_inr", "review_return_pct") if column in results.columns]
table = results[table_columns].rename(
    columns={
        "symbol": "Symbol",
        "price_inr": "Price (INR)",
        "review_return_pct": "Return (%)",
    }
)
with watchlist_column:
    st.caption(f"{len(results):,} symbols Â· {latest_date or 'date n/a'}")
    selected_rows = st.dataframe(
        table,
        hide_index=True,
        height=660,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"watchlist-{dataset_name}-{search}-{sort_label}",
        column_config={
            "Symbol": st.column_config.TextColumn(width="medium"),
            "Price (INR)": st.column_config.NumberColumn(format="%.2f", width="small"),
            "Return (%)": st.column_config.NumberColumn(format="%.2f%%", width="small"),
        },
    )
    if selected_rows.selection.rows:
        clicked_symbol = results.iloc[selected_rows.selection.rows[0]]["symbol"]
        if clicked_symbol != st.session_state["review_symbol"]:
            st.session_state["review_symbol"] = clicked_symbol
            st.rerun()

with chart_column:
    selected_symbol = st.session_state["review_symbol"]
    selected_row = results.loc[results["symbol"].eq(selected_symbol)].iloc[0]
    st.markdown(
        f'<div class="chartbar"><span><strong>{html.escape(selected_symbol)}</strong>'
        '<span class="exchange"> Â· 1D Â· NSE</span></span>'
        f'<span class="exchange">Data date {html.escape(str(latest_date or "n/a"))}</span></div>',
        unsafe_allow_html=True,
    )
    keyboard_event = chart_keyboard(symbol=selected_symbol, default=None, key="chart-keyboard")
    if isinstance(keyboard_event, dict):
        event_id = keyboard_event.get("event_id")
        direction = keyboard_event.get("direction")
        if event_id and event_id != st.session_state.get("last_chart_key_event"):
            st.session_state["last_chart_key_event"] = event_id
            offset = 1 if direction == "next" else -1 if direction == "previous" else 0
            if offset:
                move_selection(symbols, offset)
                st.rerun()

    metrics = st.columns(4)
    metrics[0].metric("Close", display_value(selected_row, "price_inr", " INR"))
    metrics[1].metric("EMA 20", display_value(selected_row, "ema20"))
    metrics[2].metric("EMA 50", display_value(selected_row, "ema50"))
    metrics[3].metric("EMA 200", display_value(selected_row, "ema200"))

    try:
        chart_image = render_chart(selected_symbol)
        if not chart_image:
            st.warning(f"No recent price history is available for {selected_symbol}.")
        else:
            st.image(chart_image, use_container_width=True)
            chart_prices = load_chart_prices(selected_symbol)
            latest_date = chart_prices.index[-1].date().isoformat()
    except Exception as error:
        st.warning(f"Could not load the latest chart for {selected_symbol}: {error}")

    st.caption("EMA 20 Â· EMA 50 Â· EMA 200")
    st.markdown(
        '<div class="hint">Use the â† / â†’ arrow keys to move through this watchlist. '
        'Keyboard shortcuts are ignored while typing in search fields.</div>',
        unsafe_allow_html=True,
    )
    details = []
    if return_column in selected_row:
        period = "60-day" if return_column == "return_60d_pct" else "3-month"
        details.append(
            f"{period} return: {display_value(selected_row, 'review_return_pct', '%')}"
        )
    if "consolidation_range_pct" in selected_row:
        details.append(
            f"Consolidation range: {display_value(selected_row, 'consolidation_range_pct', '%')}"
        )
    if "breakout" in selected_row:
        details.append(f"Breakout detected: {'Yes' if bool(selected_row['breakout']) else 'No'}")
    if "volume_support" in selected_row:
        details.append(f"Volume support: {'Yes' if bool(selected_row['volume_support']) else 'No'}")
    if details:
        st.caption("  Â·  ".join(details))

st.caption("Research view only; screener matches are not trade recommendations.")


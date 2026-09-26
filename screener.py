"""Screen Indian equities and save charts for the matching symbols.

The first-stage filters mirror the TradingView setup in the supplied image.
The second-stage filters are deliberately Python-only and are configurable in
the SETTINGS section below.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import mplfinance as mpf
import numpy as np
import pandas as pd
import yfinance as yf


# ----------------------------- Settings ------------------------------------
UNIVERSE_FILE = Path("symbols.csv")
OUTPUT_DIR = Path("screened_charts")
PERIOD = "2y"
INTERVAL = "1d"

# TradingView filters from the screenshot.
MIN_MARKET_CAP_INR = 10_000_000_000
MIN_PRICE_INR = 50
MAX_PRICE_INR = 1_200
REQUIRE_EMA_50_ABOVE_EMA_200 = True
REQUIRE_PRICE_ABOVE_EMA_200 = True
REQUIRE_EMA_20_ABOVE_EMA_50 = True

CHART_BARS = 180
PRICE_BATCH_SIZE = 100
DOWNLOAD_TIMEOUT_SECONDS = 30
SAVE_CHARTS = os.getenv("SAVE_CHARTS", "true").lower() not in {"0", "false", "no"}
MAX_SCREENING_ERRORS = int(os.getenv("MAX_SCREENING_ERRORS", "20"))


def load_universe() -> pd.DataFrame:
    """Read symbols and optional metadata from symbols.csv."""
    if not UNIVERSE_FILE.exists():
        raise FileNotFoundError(
            f"Create {UNIVERSE_FILE} with columns symbol,sector,market_cap_inr."
        )

    universe = pd.read_csv(UNIVERSE_FILE)
    required = {"symbol"}
    missing = required - set(universe.columns)
    if missing:
        raise ValueError(f"symbols.csv is missing columns: {sorted(missing)}")

    universe["symbol"] = universe["symbol"].astype(str).str.strip().str.upper()
    universe = universe[universe["symbol"].ne("")].drop_duplicates("symbol")
    if "sector" not in universe:
        universe["sector"] = ""
    if "market_cap_inr" not in universe:
        universe["market_cap_inr"] = np.nan
    return universe


def ticker_symbol(symbol: str) -> str:
    return symbol if symbol.endswith(".NS") or symbol.endswith(".BO") else f"{symbol}.NS"


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    change = series.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = -change.clip(upper=0).ewm(alpha=1 / period, adjust=False).mean()
    relative_strength = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + relative_strength))


def tradingview_ema(series: pd.Series, period: int) -> pd.Series:
    """Calculate an EMA using TradingView's standard SMA-seeded recursion."""
    values = pd.to_numeric(series, errors="coerce")
    ema = pd.Series(np.nan, index=values.index, dtype="float64")
    valid = values.dropna()
    if len(valid) < period:
        return ema

    alpha = 2 / (period + 1)
    seed_position = values.index.get_loc(valid.index[period - 1])
    ema.iloc[seed_position] = valid.iloc[:period].mean()

    for position in range(seed_position + 1, len(values)):
        if pd.isna(values.iloc[position]):
            ema.iloc[position] = ema.iloc[position - 1]
        else:
            ema.iloc[position] = (
                alpha * values.iloc[position]
                + (1 - alpha) * ema.iloc[position - 1]
            )
    return ema


def enrich_metadata(symbol: str, row: pd.Series) -> tuple[str, float]:
    """Load market capitalization without requesting sector metadata."""
    market_cap = pd.to_numeric(row.get("market_cap_inr"), errors="coerce")
    ticker = ticker_symbol(symbol)
    if pd.notna(market_cap):
        return ticker, float(market_cap)

    info = yf.Ticker(ticker).get_info()
    return ticker, float(info.get("marketCap", np.nan))


def download_prices(ticker: str) -> pd.DataFrame:
    prices = yf.download(
        ticker, period=PERIOD, interval=INTERVAL, auto_adjust=False,
        progress=False, threads=False, timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )
    if prices.empty:
        return prices
    if isinstance(prices.columns, pd.MultiIndex):
        prices.columns = prices.columns.get_level_values(0)
    return prices.dropna(subset=["Open", "High", "Low", "Close"])


def download_price_batch(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Download daily prices for many tickers in one Yahoo request."""
    downloaded = yf.download(
        tickers, period=PERIOD, interval=INTERVAL, auto_adjust=False,
        progress=False, threads=True, group_by="ticker",
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )
    prices_by_ticker: dict[str, pd.DataFrame] = {}
    if downloaded.empty:
        return prices_by_ticker

    for ticker in tickers:
        try:
            prices = downloaded[ticker].dropna(
                subset=["Open", "High", "Low", "Close"]
            )
            if not prices.empty:
                prices_by_ticker[ticker] = prices
        except (KeyError, TypeError):
            continue
    return prices_by_ticker


def passes_filters(prices: pd.DataFrame, market_cap: float) -> dict:
    close = prices["Close"]
    prices = prices.copy()
    prices["EMA20"] = tradingview_ema(close, 20)
    prices["EMA50"] = tradingview_ema(close, 50)
    prices["EMA200"] = tradingview_ema(close, 200)
    prices["RSI14"] = rsi(close)
    prices["AvgVolume20"] = prices["Volume"].rolling(20).mean()

    latest = prices.iloc[-1]
    return {
        "market_cap_inr": market_cap,
        "price_inr": float(latest["Close"]),
        "ema20": float(latest["EMA20"]),
        "ema50": float(latest["EMA50"]),
        "ema200": float(latest["EMA200"]),
        "rsi14": float(latest["RSI14"]),
        "avg_volume_20": float(latest["AvgVolume20"]),
        "return_3m": float(close.iloc[-1] / close.iloc[-64] - 1) if len(close) >= 64 else np.nan,
        "volume_breakout": bool(latest["Volume"] > latest["AvgVolume20"] * 1.5),
        "_prices": prices,
    }


def passes_configured_filters(metrics: dict) -> bool:
    """Match the visible TradingView filters, excluding sector."""
    price = metrics["price_inr"]
    if not MIN_MARKET_CAP_INR <= metrics["market_cap_inr"]:
        return False
    if not MIN_PRICE_INR <= price <= MAX_PRICE_INR:
        return False
    if REQUIRE_EMA_50_ABOVE_EMA_200 and not metrics["ema50"] > metrics["ema200"]:
        return False
    if REQUIRE_PRICE_ABOVE_EMA_200 and not price > metrics["ema200"]:
        return False
    if REQUIRE_EMA_20_ABOVE_EMA_50 and not metrics["ema20"] > metrics["ema50"]:
        return False
    return True


def passes_technical_filters(metrics: dict) -> bool:
    """Apply the TradingView price and EMA filters before market-cap lookup."""
    price = metrics["price_inr"]
    if not MIN_PRICE_INR <= price <= MAX_PRICE_INR:
        return False
    if REQUIRE_EMA_50_ABOVE_EMA_200 and not metrics["ema50"] > metrics["ema200"]:
        return False
    if REQUIRE_PRICE_ABOVE_EMA_200 and not price > metrics["ema200"]:
        return False
    if REQUIRE_EMA_20_ABOVE_EMA_50 and not metrics["ema20"] > metrics["ema50"]:
        return False
    return True


def save_chart(ticker: str, metrics: dict) -> None:
    prices = metrics["_prices"].tail(CHART_BARS)
    addplots = [
        mpf.make_addplot(prices["EMA20"], color="#f59e0b", width=1),
        mpf.make_addplot(prices["EMA50"], color="#2563eb", width=1),
        mpf.make_addplot(prices["EMA200"], color="#dc2626", width=1),
    ]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    name = ticker.replace(".NS", "").replace(".BO", "")
    title = f"{name} | Close {metrics['price_inr']:.2f} | RSI {metrics['rsi14']:.1f}"
    mpf.plot(
        prices, type="candle", style="yahoo", volume=True, addplot=addplots,
        title=title, savefig=OUTPUT_DIR / f"{name}.png", figsize=(14, 8),
    )


def main() -> None:
    universe = load_universe()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    rows = list(universe.iterrows())
    tradingview_matches = 0
    latest_data_date = None
    screening_errors = 0
    for start in range(0, len(rows), PRICE_BATCH_SIZE):
        batch = rows[start:start + PRICE_BATCH_SIZE]
        tickers = [ticker_symbol(row["symbol"]) for _, row in batch]
        print(
            f"Downloading batch {start + 1}-{start + len(batch)}/{len(rows)}",
            flush=True,
        )
        try:
            price_data = download_price_batch(tickers)
        except Exception as error:
            screening_errors += len(batch)
            print(f"ERROR downloading batch {start + 1}-{start + len(batch)}: {error}")
            continue

        for _, row in batch:
            symbol = row["symbol"]
            ticker = ticker_symbol(symbol)
            prices = price_data.get(ticker, pd.DataFrame())
            if len(prices) < 220:
                continue
            try:
                metrics = passes_filters(prices, np.nan)
                latest_data_date = prices.index[-1].date()
                if not passes_technical_filters(metrics):
                    continue
                _, market_cap = enrich_metadata(symbol, row)
                metrics["market_cap_inr"] = market_cap
                metrics["latest_data_date"] = prices.index[-1].date()
                if passes_configured_filters(metrics):
                    tradingview_matches += 1
                    if SAVE_CHARTS:
                        save_chart(ticker, metrics)
                    results.append({k: v for k, v in metrics.items() if k != "_prices"} | {"symbol": symbol})
                    print(f"MATCH  {symbol}")
            except Exception as error:
                screening_errors += 1
                print(f"ERROR   {symbol}: {error}")
        print(
            f"Processed {min(start + len(batch), len(rows))}/{len(rows)} stocks",
            flush=True,
        )

    if screening_errors > MAX_SCREENING_ERRORS:
        raise RuntimeError(
            f"Aborting without publishing screener results: {screening_errors} "
            f"symbol/batch errors exceed the limit of {MAX_SCREENING_ERRORS}."
        )

    output = pd.DataFrame(results)
    output.to_csv(OUTPUT_DIR / "matches.csv", index=False)
    print(f"\nTradingView-equivalent matches: {tradingview_matches}")
    print(f"Latest price data date observed: {latest_data_date}")
    print(f"Saved {len(output)} chart match(es) to {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()

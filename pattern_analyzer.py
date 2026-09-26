"""Find bullish chart structures similar to the supplied sample chart.

This is a heuristic second-stage analysis over screened_charts/matches.csv.
It looks for aligned rising EMAs, price strength, a tight recent range, and a
recent breakout with supporting volume. It does not change the base screener.
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

from screener import (
    CHART_BARS,
    DOWNLOAD_TIMEOUT_SECONDS,
    PERIOD,
    PRICE_BATCH_SIZE,
    tradingview_ema,
    ticker_symbol,
)


INPUT_FILE = Path("screened_charts/matches.csv")
OUTPUT_DIR = Path("pattern_charts")
OUTPUT_FILE = OUTPUT_DIR / "pattern_matches.csv"

# Pattern settings. These are intentionally slightly looser than the original
# strict heuristic so visually similar bullish breakouts are not missed.
CONSOLIDATION_BARS = 20
CONSOLIDATION_MAX_RANGE = 0.25
BREAKOUT_LOOKBACK_BARS = 5
BREAKOUT_VOLUME_MULTIPLIER = 1.00
MIN_60_DAY_RETURN = 0.02
REQUIRE_RISING_EMAS = True
PATTERN_BATCH_SIZE = 25
SAVE_CHARTS = os.getenv("SAVE_CHARTS", "true").lower() not in {"0", "false", "no"}
MAX_PATTERN_DATA_ERRORS = int(os.getenv("MAX_PATTERN_DATA_ERRORS", "20"))


def download_price_batch(tickers: list[str]) -> dict[str, pd.DataFrame]:
    downloaded = yf.download(
        tickers,
        period=PERIOD,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=True,
        group_by="ticker",
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )
    result: dict[str, pd.DataFrame] = {}
    if downloaded.empty:
        return result

    for ticker in tickers:
        try:
            prices = downloaded[ticker].dropna(
                subset=["Open", "High", "Low", "Close"]
            )
            if not prices.empty:
                result[ticker] = prices
        except (KeyError, TypeError):
            continue
    return result


def analyze_pattern(prices: pd.DataFrame) -> dict | None:
    if len(prices) < 220:
        return None

    prices = prices.copy()
    close = prices["Close"]
    prices["EMA20"] = tradingview_ema(close, 20)
    prices["EMA50"] = tradingview_ema(close, 50)
    prices["EMA200"] = tradingview_ema(close, 200)
    prices["AvgVolume20"] = prices["Volume"].rolling(20).mean()
    latest = prices.iloc[-1]

    consolidation = prices.iloc[-CONSOLIDATION_BARS - BREAKOUT_LOOKBACK_BARS:-BREAKOUT_LOOKBACK_BARS]
    if len(consolidation) < CONSOLIDATION_BARS:
        return None

    consolidation_high = float(consolidation["High"].max())
    consolidation_low = float(consolidation["Low"].min())
    consolidation_range = (consolidation_high - consolidation_low) / consolidation_low
    breakout_window = prices.iloc[-BREAKOUT_LOOKBACK_BARS:]
    breakout = float(breakout_window["Close"].max()) > consolidation_high
    volume_support = float(breakout_window["Volume"].max()) >= float(
        prices["AvgVolume20"].iloc[-BREAKOUT_LOOKBACK_BARS:].max()
    ) * BREAKOUT_VOLUME_MULTIPLIER
    return_60d = float(close.iloc[-1] / close.iloc[-61] - 1)
    ema_alignment = bool(latest["EMA20"] > latest["EMA50"] > latest["EMA200"])
    ema_rising = bool(
        prices["EMA20"].iloc[-1] > prices["EMA20"].iloc[-11]
        and prices["EMA50"].iloc[-1] > prices["EMA50"].iloc[-11]
        and prices["EMA200"].iloc[-1] > prices["EMA200"].iloc[-11]
    )

    matches = (
        ema_alignment
        and (not REQUIRE_RISING_EMAS or ema_rising)
        and float(latest["Close"]) > float(latest["EMA20"])
        and consolidation_range <= CONSOLIDATION_MAX_RANGE
        and breakout
        and volume_support
        and return_60d >= MIN_60_DAY_RETURN
    )
    if not matches:
        return None

    return {
        "pattern": "bullish_ema_consolidation_breakout",
        "price_inr": float(latest["Close"]),
        "ema20": float(latest["EMA20"]),
        "ema50": float(latest["EMA50"]),
        "ema200": float(latest["EMA200"]),
        "consolidation_range_pct": consolidation_range * 100,
        "consolidation_high": consolidation_high,
        "breakout": breakout,
        "volume_support": volume_support,
        "return_60d_pct": return_60d * 100,
        "latest_data_date": prices.index[-1].date(),
        "_prices": prices,
    }


def save_pattern_chart(ticker: str, metrics: dict) -> None:
    prices = metrics["_prices"].tail(CHART_BARS)
    addplots = [
        mpf.make_addplot(prices["EMA20"], color="#f59e0b", width=1),
        mpf.make_addplot(prices["EMA50"], color="#2563eb", width=1),
        mpf.make_addplot(prices["EMA200"], color="#dc2626", width=1),
    ]
    name = ticker.replace(".NS", "").replace(".BO", "")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    title = (
        f"{name} | bullish consolidation breakout | "
        f"Close {metrics['price_inr']:.2f}"
    )
    mpf.plot(
        prices,
        type="candle",
        style="yahoo",
        volume=True,
        addplot=addplots,
        title=title,
        savefig=OUTPUT_DIR / f"{name}.png",
        figsize=(14, 8),
    )


def main() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Run the base screener first: {INPUT_FILE}")

    screened = pd.read_csv(INPUT_FILE)
    symbols = screened["symbol"].dropna().astype(str).str.upper().drop_duplicates().tolist()
    results: list[dict] = []
    data_errors = 0
    for start in range(0, len(symbols), PATTERN_BATCH_SIZE):
        batch_symbols = symbols[start:start + PATTERN_BATCH_SIZE]
        tickers = [ticker_symbol(symbol) for symbol in batch_symbols]
        print(f"Analyzing pattern batch {start + 1}-{start + len(tickers)}/{len(symbols)}", flush=True)
        try:
            price_data = download_price_batch(tickers)
        except Exception as error:
            data_errors += len(batch_symbols)
            print(f"ERROR batch: {error}")
            continue

        for symbol, ticker in zip(batch_symbols, tickers):
            prices = price_data.get(ticker, pd.DataFrame())
            if prices.empty:
                data_errors += 1
                continue
            metrics = analyze_pattern(prices)
            if metrics is None:
                continue
            if SAVE_CHARTS:
                save_pattern_chart(ticker, metrics)
            results.append({k: v for k, v in metrics.items() if k != "_prices"} | {"symbol": symbol})
            print(f"PATTERN MATCH  {symbol}", flush=True)

    if data_errors > MAX_PATTERN_DATA_ERRORS:
        raise RuntimeError(
            f"Aborting without publishing pattern results: {data_errors} "
            f"symbols lack downloaded history; the limit is {MAX_PATTERN_DATA_ERRORS}."
        )

    output_columns = [
        "pattern",
        "price_inr",
        "ema20",
        "ema50",
        "ema200",
        "consolidation_range_pct",
        "consolidation_high",
        "breakout",
        "volume_support",
        "return_60d_pct",
        "latest_data_date",
        "symbol",
    ]
    output = pd.DataFrame(results, columns=output_columns)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_FILE, index=False)
    print(f"\nPattern matches: {len(output)}")
    print(f"Saved charts and results to {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()

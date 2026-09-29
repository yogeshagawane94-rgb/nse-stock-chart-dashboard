"""Download the current listed-equity universe from the official NSE CSV."""

from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd


NSE_EQUITY_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
OUTPUT_FILE = Path("symbols.csv")
MATCHES_FILE = Path("screened_charts") / "matches.csv"


def load_market_cap_cache() -> dict[str, float]:
    """Keep known caps across universe refreshes, including prior matches."""
    cached: dict[str, float] = {}
    for path in (OUTPUT_FILE, MATCHES_FILE):
        if not path.exists():
            continue
        try:
            previous = pd.read_csv(path, usecols=["symbol", "market_cap_inr"])
        except (ValueError, pd.errors.EmptyDataError):
            continue
        previous["symbol"] = previous["symbol"].astype(str).str.strip().str.upper()
        previous["market_cap_inr"] = pd.to_numeric(
            previous["market_cap_inr"], errors="coerce"
        )
        for symbol, market_cap in previous[["symbol", "market_cap_inr"]].itertuples(
            index=False, name=None
        ):
            if symbol and pd.notna(market_cap) and market_cap > 0:
                cached[symbol] = float(market_cap)
    return cached


def main() -> None:
    market_cap_cache = load_market_cap_cache()
    request = Request(NSE_EQUITY_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=60) as response:
        nse_data = pd.read_csv(response)
    nse_data.columns = nse_data.columns.str.replace("\ufeff", "", regex=False).str.strip()

    equities = nse_data.loc[
        nse_data["SERIES"].eq("EQ"), ["SYMBOL", "NAME OF COMPANY"]
    ].copy()
    equities = equities.rename(columns={"SYMBOL": "symbol"})
    equities["symbol"] = equities["symbol"].astype(str).str.strip().str.upper()
    equities["sector"] = ""
    equities["market_cap_inr"] = equities["symbol"].map(market_cap_cache)
    equities["market_cap_inr"] = equities["market_cap_inr"].fillna("")
    equities = equities[["symbol", "sector", "market_cap_inr"]].drop_duplicates()
    equities.to_csv(OUTPUT_FILE, index=False)
    print(
        f"Saved {len(equities)} NSE equity symbols to {OUTPUT_FILE.resolve()} "
        f"({equities['market_cap_inr'].astype(str).ne('').sum()} cached market caps)"
    )


if __name__ == "__main__":
    main()

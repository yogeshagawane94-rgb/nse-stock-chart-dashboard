"""Download the current listed-equity universe from the official NSE CSV."""

from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd


NSE_EQUITY_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
OUTPUT_FILE = Path("symbols.csv")


def main() -> None:
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
    equities["market_cap_inr"] = ""
    equities = equities[["symbol", "sector", "market_cap_inr"]].drop_duplicates()
    equities.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved {len(equities)} NSE equity symbols to {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()

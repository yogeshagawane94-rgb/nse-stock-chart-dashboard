# Indian equity screener

This script reproduces the visible TradingView filters and then applies extra
filters locally in Python. It uses Yahoo Finance data, so it is independent of
the TradingView Basic/Premium feature limit.

## Filters

The base filters are:

- Market cap `> 10B INR`
- Price between `50 INR` and `1200 INR`
- `EMA(50) > EMA(200)`
- Price `> EMA(200)`
- `EMA(20) > EMA(50)`
- India-listed symbols, using the `.NS` ticker suffix by default

Sector is intentionally not used. `symbols.csv` may retain its `sector` column,
but it is ignored. The script only obtains market capitalization from Yahoo
Finance when `market_cap_inr` is blank.

No additional RSI, volume, return, or sector filters are applied, so the final
count is directly comparable with the TradingView filter count.

## Run

Refresh the full NSE equity universe before screening:

```powershell
python download_nse_universe.py
```

This downloads active `EQ` series equities from the official NSE equity
master. The NSE file does not contain market capitalization or sector, so the
screener fills those fields from Yahoo Finance while processing each symbol.

Then run the screener:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python screener.py
```

The script writes `screened_charts/matches.csv` and one PNG candlestick chart
per match, with EMA 20, 50, and 200 overlaid. Replace the sample row in
`symbols.csv` with the symbols you want to screen. A broad NSE universe can be
generated separately and saved in the same format; keeping the universe local
makes the script more reliable and avoids depending on an undocumented
TradingView endpoint.

## Stock review dashboard

After generating the screener or pattern results, start the local dashboard:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run dashboard.py
```

The dashboard lets you switch between all base screener matches and the
second-stage pattern matches, search and sort symbols, and review each saved
chart with its available EMA and pattern metrics.

## Public cloud deployment

Streamlit Community Cloud apps and their GitHub repository contents are
public. Do not put credentials, personal information, or private files in this
repository. The `.gitignore` excludes the local virtual environment, logs,
caches, and Streamlit secrets while retaining the generated chart images and
CSV files used by the dashboard.

To deploy, push this project to a public GitHub repository, sign in at
[Streamlit Community Cloud](https://share.streamlit.io/), create an app from
that repository, and set the entry point to `dashboard.py`. Keep
`requirements.txt`, `components/chart_keyboard/index.html`, and both chart
output folders in the repository. Updates to repository files are reflected
in the hosted app; daily data refresh still needs a scheduled workflow.

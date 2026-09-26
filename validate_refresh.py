from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BASE_RESULTS = ROOT / "screened_charts" / "matches.csv"
PATTERN_RESULTS = ROOT / "pattern_charts" / "pattern_matches.csv"
MAX_DATA_AGE_DAYS = 10


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"Expected results file was not generated: {path}")
    with path.open(newline="", encoding="utf-8") as result_file:
        reader = csv.DictReader(result_file)
        return reader.fieldnames or [], list(reader)


def main() -> None:
    base_columns, base_rows = read_rows(BASE_RESULTS)
    if not {"symbol", "latest_data_date"}.issubset(base_columns):
        raise ValueError("Base screener CSV lacks symbol or latest_data_date columns.")
    if not base_rows:
        raise ValueError("Base screener returned no matches; refusing to publish empty data.")

    latest_date = max(
        date.fromisoformat(row["latest_data_date"])
        for row in base_rows
        if row.get("latest_data_date")
    )
    age_days = (datetime.now().date() - latest_date).days
    if age_days < 0 or age_days > MAX_DATA_AGE_DAYS:
        raise ValueError(
            f"Latest screener data date {latest_date} is {age_days} days old; "
            "refusing to publish stale results."
        )

    pattern_columns, pattern_rows = read_rows(PATTERN_RESULTS)
    if "symbol" not in pattern_columns:
        raise ValueError("Pattern results CSV lacks its symbol column.")

    print(
        f"Validated {len(base_rows)} base matches and {len(pattern_rows)} "
        f"pattern matches; latest market data date is {latest_date}."
    )


if __name__ == "__main__":
    main()
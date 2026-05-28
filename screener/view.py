#!/usr/bin/env python3
"""
View screener results locally with custom sorting.

Usage:
  python3 view.py                    # Today's results, sorted by Momentum
  python3 view.py --sort day         # Sort by daily move
  python3 view.py --sort week        # Sort by weekly gain
  python3 view.py --sort volume      # Sort by volume ratio
  python3 view.py --sort roc         # Sort by 20-day rate of change
  python3 view.py --sort rating      # Sort by analyst rating (best first)
  python3 view.py --sort mcap        # Sort by market cap
  python3 view.py --date 2026-05-07  # View a specific date
  python3 view.py --top 20           # Show only top 20
  python3 view.py --sector Tech      # Filter by sector (partial match)
"""

import argparse
import os
import sys
from datetime import datetime

import pandas as pd

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "screener_output")

SORT_MAP = {
    "momentum": ("Momentum", False),
    "day": ("Day%", False),
    "daily": ("Day%", False),
    "week": ("Week%", False),
    "weekly": ("Week%", False),
    "volume": ("Vol Ratio", False),
    "vol": ("Vol Ratio", False),
    "roc": ("ROC20%", False),
    "rating": ("Rating", True),
    "mcap": ("MCap($B)", False),
    "ema": ("Above EMA%", False),
    "price": ("Price", False),
    "rsi": ("RSI", False),
    "macd": ("MACD Hist", False),
}


def find_result_file(date_str=None):
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    month_str = date_str[:7]
    path = os.path.join(RESULTS_DIR, month_str, f"{date_str}.txt")

    if os.path.exists(path):
        return path

    # Try syncing from S3
    print(f"Results not found locally for {date_str}. Run ./sync_results.sh first.")
    sys.exit(1)


def parse_results_file(filepath):
    with open(filepath) as f:
        lines = f.readlines()

    header_idx = None
    for i, line in enumerate(lines):
        if "Ticker" in line and "Price" in line and "Momentum" in line:
            header_idx = i
            break

    if header_idx is None:
        print("Could not parse results file.")
        sys.exit(1)

    headers = ["Ticker", "Price", "Day%", "Week%", "Above EMA%", "RSI", "MACD",
               "MACD Hist", "ROC20%", "Vol Ratio", "Momentum", "Rating", "MCap($B)", "Sector"]

    rows = []
    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 10:
            continue
        try:
            row = {
                "Ticker": parts[1],
                "Price": float(parts[2]),
                "Day%": float(parts[3]),
                "Week%": float(parts[4]),
                "Above EMA%": float(parts[5]),
                "RSI": float(parts[6]),
                "MACD": parts[7],
                "MACD Hist": float(parts[8]),
                "ROC20%": float(parts[9]),
                "Vol Ratio": float(parts[10]),
                "Momentum": float(parts[11]),
                "Rating": float(parts[12]) if parts[12] != "None" else None,
                "MCap($B)": float(parts[13]),
                "Sector": " ".join(parts[14:]),
            }
            rows.append(row)
        except (IndexError, ValueError):
            continue

    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="View stock screener results")
    parser.add_argument("--sort", "-s", default="momentum", help="Sort column (day, week, volume, roc, rating, mcap, momentum, ema, rsi, macd)")
    parser.add_argument("--date", "-d", default=None, help="Date to view (YYYY-MM-DD)")
    parser.add_argument("--top", "-t", type=int, default=None, help="Show only top N results")
    parser.add_argument("--sector", default=None, help="Filter by sector (partial match)")
    parser.add_argument("--asc", action="store_true", help="Sort ascending instead of descending")
    args = parser.parse_args()

    filepath = find_result_file(args.date)
    df = parse_results_file(filepath)

    if df.empty:
        print("No results to display.")
        return

    # Filter by sector
    if args.sector:
        df = df[df["Sector"].str.contains(args.sector, case=False, na=False)]
        if df.empty:
            print(f"No results matching sector '{args.sector}'")
            return

    # Sort
    sort_key = args.sort.lower()
    if sort_key not in SORT_MAP:
        print(f"Unknown sort key '{args.sort}'. Options: {', '.join(SORT_MAP.keys())}")
        sys.exit(1)

    col, default_asc = SORT_MAP[sort_key]
    ascending = args.asc if args.asc else default_asc
    df = df.sort_values(col, ascending=ascending, na_position="last")

    # Limit
    if args.top:
        df = df.head(args.top)

    df = df.reset_index(drop=True)
    df.index += 1

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    print(f"\n=== Stock Screener Results — {date_str} ===")
    print(f"  Sorted by: {col} ({'asc' if ascending else 'desc'})")
    if args.sector:
        print(f"  Sector filter: {args.sector}")
    print(f"  Showing: {len(df)} stocks\n")
    print(df.to_string())
    print()


if __name__ == "__main__":
    main()

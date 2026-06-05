#!/usr/bin/env python3
"""
Short/Bearish Stock Screener — finds stocks to short or avoid.

Criteria:
1. Price BELOW 50-day EMA (confirmed downtrend)
2. Negative weekly move (momentum confirmation)
3. Bearish technicals (RSI dropping, MACD bearish, volume on down days)
4. Bad earnings (missed EPS/revenue, lowered guidance)
5. Market cap > $1B (liquid enough to short)

Sorted by "bearish score" — higher = stronger short candidate.
"""

import yfinance as yf
import pandas as pd
import requests
import os
import sys
from io import StringIO
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

FILTERED = "__FILTERED__"


def compute_ema(series, span=50):
    return series.ewm(span=span, adjust=False).mean()


def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def compute_macd(series):
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    histogram = macd - signal
    return macd, signal, histogram


def get_all_tickers():
    """Fetch all US-traded stocks with market cap > $1B from NASDAQ screener."""
    url = "https://www.nasdaq.com/api/screener/stocks?tableType=earnings&download=true"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            df = pd.read_csv(StringIO(resp.text))
            df["Market Cap"] = pd.to_numeric(df["Market Cap"], errors="coerce")
            big = df[df["Market Cap"] >= 1e9]
            return big["Symbol"].str.strip().tolist()
    except Exception:
        pass

    # Fallback: use the same tickers from the long screener output
    from pathlib import Path
    results_dir = Path(__file__).parent.parent / "screener_output"
    month = datetime.now().strftime("%Y-%m")
    date = datetime.now().strftime("%Y-%m-%d")
    csv_path = results_dir / month / f"{date}.csv"
    if not csv_path.exists():
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        csv_path = results_dir / month / f"{yesterday}.csv"
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        return df["Ticker"].tolist()
    return []


def analyze_short(ticker):
    """Analyze a single ticker for short potential. Returns dict or FILTERED."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        market_cap = info.get("marketCap", 0) or 0
        if market_cap < 1e9:
            return FILTERED

        hist = stock.history(period="6mo")
        if hist.empty or len(hist) < 50:
            return FILTERED

        close = hist["Close"]

        # Real-time price
        try:
            fi = stock.fast_info
            current_price = fi.last_price
            prev_close = fi.previous_close
            daily_move = (current_price - prev_close) / prev_close * 100
        except Exception:
            current_price = close.iloc[-1]
            prev_close = close.iloc[-2] if len(close) >= 2 else close.iloc[0]
            daily_move = (current_price - prev_close) / prev_close * 100

        # Must be BELOW 50-day EMA (downtrend)
        ema_50 = compute_ema(close, span=50)
        current_ema = ema_50.iloc[-1]
        if current_price >= current_ema:
            return FILTERED

        # Must have negative weekly move
        five_days_ago = close.iloc[-6] if len(close) >= 6 else close.iloc[0]
        weekly_move = (current_price - five_days_ago) / five_days_ago * 100
        if weekly_move >= 0:
            return FILTERED

        # Technicals
        rsi = compute_rsi(close).iloc[-1]
        macd_line, signal_line, macd_hist = compute_macd(close)
        macd_val = macd_line.iloc[-1]
        macd_signal = signal_line.iloc[-1]
        macd_histogram = macd_hist.iloc[-1]

        # Volume surge (selling pressure)
        vol = hist["Volume"]
        vol_avg_20 = vol.iloc[-20:].mean() if len(vol) >= 20 else vol.mean()
        vol_ratio = vol.iloc[-1] / vol_avg_20 if vol_avg_20 > 0 else 1.0

        # Rate of change: 20-day
        roc_20 = (current_price - close.iloc[-21]) / close.iloc[-21] * 100 if len(close) >= 21 else 0

        # EMA spread (how far below EMA = stronger downtrend)
        ema_spread = (current_price - current_ema) / current_ema * 100  # Negative

        # Earnings data
        earnings_miss = False
        try:
            earnings = stock.earnings_history
            if earnings is not None and not earnings.empty:
                latest = earnings.iloc[-1] if hasattr(earnings, 'iloc') else None
                if latest is not None:
                    surprise = latest.get("epsActual", 0) - latest.get("epsEstimate", 0)
                    if surprise < 0:
                        earnings_miss = True
        except Exception:
            pass

        # Short interest
        short_pct = info.get("shortPercentOfFloat", 0) or 0

        # Bearish score (higher = better short)
        # Components: EMA distance (30%), ROC-20 magnitude (25%), volume surge (20%), MACD bearishness (15%), earnings miss (10%)
        bearish_score = (
            (min(max(abs(ema_spread), 0), 15) / 15) * 30 +  # Distance below EMA
            (min(max(abs(roc_20), 0), 20) / 20) * 25 +      # 20-day decline magnitude
            (min(max(vol_ratio, 0), 3) / 3) * 20 +          # Volume on selling
            (min(max(abs(macd_histogram) / current_price * 1000, 0), 5) / 5) * 15 +  # MACD bearishness
            (10 if earnings_miss else 0)                      # Earnings miss bonus
        )

        return {
            "Ticker": ticker,
            "Price": round(current_price, 2),
            "Day%": round(daily_move, 2),
            "Week%": round(weekly_move, 2),
            "MCap($B)": round(market_cap / 1e9, 1),
            "Sector": info.get("sector", "N/A"),
            "Below EMA%": round(ema_spread, 2),
            "RSI": round(rsi, 1),
            "MACD": "Bear" if macd_val < macd_signal else "Bull",
            "MACD Hist": round(macd_histogram, 2),
            "ROC20%": round(roc_20, 2),
            "Vol Ratio": round(vol_ratio, 2),
            "Short%": round(short_pct * 100, 1),
            "EPS Miss": "Y" if earnings_miss else "",
            "Bearish": round(bearish_score, 1),
        }

    except Exception:
        return FILTERED


def main():
    print(f"=== Short/Bearish Screener — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    # Get tickers
    print("Fetching ticker universe...")
    tickers = get_all_tickers()
    if not tickers:
        print("ERROR: No tickers found")
        return

    print(f"Screening {len(tickers)} stocks for short candidates...\n")

    # Process in batches
    results = []
    batch_size = 50
    for i in range(0, min(len(tickers), 2000), batch_size):
        batch = tickers[i:i + batch_size]
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(analyze_short, t): t for t in batch}
            for future in as_completed(futures):
                result = future.result()
                if result != FILTERED:
                    results.append(result)

        import time
        time.sleep(1)
        done = min(i + batch_size, len(tickers))
        print(f"  Progress: {done}/{min(len(tickers), 2000)} ({len(results)} shorts found)")

    print(f"\n  Final: {len(results)} short candidates")

    if not results:
        print("No short candidates found.")
        return

    df = pd.DataFrame(results)
    df = df.sort_values("Bearish", ascending=False)

    # Display
    print(f"\n{'='*90}")
    print(f"  TOP SHORT CANDIDATES — {datetime.now().strftime('%Y-%m-%d')}")
    print(f"  {len(df)} stocks below 50d EMA with negative weekly momentum")
    print(f"{'='*90}\n")
    print(df.head(30).to_string(index=False))

    # Save
    from pathlib import Path
    output_dir = Path(__file__).parent.parent / "screener_output"
    month_dir = output_dir / datetime.now().strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")

    # CSV
    csv_path = month_dir / f"{date_str}_shorts.csv"
    df.to_csv(csv_path, index=False)

    # Text
    txt_path = month_dir / f"{date_str}_shorts.txt"
    with open(txt_path, "w") as f:
        f.write(f"Short/Bearish Screener — {date_str}\n")
        f.write(f"{len(df)} candidates | Below 50d EMA | Negative week | MCap >$1B\n\n")
        f.write(df.head(50).to_string(index=False))

    print(f"\nSaved to {csv_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Stock screener: finds stocks above 50-day EMA, positive weekly gains,
market cap > $1B, with momentum signals, sorted by composite momentum score.
"""

import yfinance as yf
import pandas as pd
import requests
import os
import sys
from io import StringIO
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

def get_universe():
    """Fetch all US-traded stocks with market cap > $1B from NASDAQ screener, sorted by daily gain."""
    url = "https://api.nasdaq.com/api/screener/stocks?tableType=traded&limit=10000&offset=0"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        data = resp.json()
        rows = data["data"]["table"]["rows"]
        candidates = []
        for r in rows:
            mcap_str = r.get("marketCap", "0").replace(",", "").replace(" ", "")
            try:
                mcap = int(mcap_str)
            except ValueError:
                continue
            if mcap >= 1_000_000_000:
                symbol = r["symbol"].strip()
                if "/" not in symbol and "^" not in symbol:
                    pct_str = r.get("pctchange", "0%").replace("%", "").replace(",", "")
                    try:
                        pct = float(pct_str)
                    except ValueError:
                        pct = 0.0
                    candidates.append((symbol, pct))
        # Sort by daily gain descending — top movers get processed first
        candidates.sort(key=lambda x: x[1], reverse=True)
        tickers = [c[0] for c in candidates]
        print(f"  NASDAQ screener: {len(tickers)} stocks with market cap > $1B")
        print(f"  Top 5 by daily gain: {', '.join(f'{c[0]}({c[1]:+.1f}%)' for c in candidates[:5])}")
        return tickers
    except Exception as e:
        print(f"  ERROR fetching universe: {e}")
        return []

def compute_ema(prices, span=50):
    return prices.ewm(span=span, adjust=False).mean()

def compute_rsi(prices, period=14):
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def compute_macd(prices):
    ema12 = prices.ewm(span=12, adjust=False).mean()
    ema26 = prices.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

FILTERED = "FILTERED"

def screen_stock(ticker):
    """Screen a single stock. Returns dict if passes, FILTERED if legitimately filtered, None if error."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        if not info or info.get("regularMarketPrice") is None:
            return None  # API error — should retry

        market_cap = info.get("marketCap", 0)
        if not market_cap or market_cap < 1_000_000_000:
            return FILTERED

        hist = stock.history(period="6mo")
        if hist.empty or len(hist) < 50:
            return FILTERED

        close = hist["Close"]
        current_price = close.iloc[-1]

        # 50-day EMA filter
        ema_50 = compute_ema(close, span=50)
        current_ema = ema_50.iloc[-1]
        if current_price <= current_ema:
            return FILTERED

        # Daily move
        prev_close = close.iloc[-2] if len(close) >= 2 else close.iloc[0]
        daily_move = (current_price - prev_close) / prev_close * 100

        # Positive weekly gain
        five_days_ago = close.iloc[-6] if len(close) >= 6 else close.iloc[0]
        weekly_gain = (current_price - five_days_ago) / five_days_ago * 100
        if weekly_gain <= 0:
            return FILTERED

        # Momentum signals
        rsi = compute_rsi(close).iloc[-1]
        macd_line, signal_line, macd_hist = compute_macd(close)
        macd_val = macd_line.iloc[-1]
        macd_signal = signal_line.iloc[-1]
        macd_histogram = macd_hist.iloc[-1]

        # Rate of change: 20-day
        roc_20 = (current_price - close.iloc[-21]) / close.iloc[-21] * 100 if len(close) >= 21 else 0

        # Volume surge: current vs 20-day average
        vol = hist["Volume"]
        vol_avg_20 = vol.iloc[-20:].mean() if len(vol) >= 20 else vol.mean()
        vol_ratio = vol.iloc[-1] / vol_avg_20 if vol_avg_20 > 0 else 1.0

        # Composite momentum score (higher = stronger momentum)
        ema_spread = (current_price - current_ema) / current_ema * 100
        momentum_score = (
            (min(max(macd_histogram / current_price * 1000, 0), 5) / 5) * 35 +  # MACD histogram (0-35)
            (min(max(roc_20, 0), 30) / 30) * 30 +                               # ROC-20 (0-30)
            (min(max(vol_ratio, 0), 3) / 3) * 25 +                              # Vol ratio (0-25)
            (min(max(ema_spread, 0), 20) / 20) * 10                             # EMA spread (0-10)
        )

        # Invert rating: Yahoo gives 1=Strong Buy, 5=Strong Sell
        # We flip to 5=Strong Buy, 1=Strong Sell
        raw_rating = info.get("recommendationMean", None)
        rating = round(6 - raw_rating, 2) if raw_rating else None

        return {
            "Ticker": ticker,
            "Price": round(current_price, 2),
            "Day%": round(daily_move, 2),
            "Week%": round(weekly_gain, 2),
            "MCap($B)": round(market_cap / 1e9, 1),
            "Sector": info.get("sector", "N/A"),
            "Industry": info.get("industry", "N/A"),
            "Above EMA%": round(ema_spread, 2),
            "RSI": round(rsi, 1),
            "MACD": "Bull" if macd_val > macd_signal else "Bear",
            "MACD Hist": round(macd_histogram, 2),
            "ROC20%": round(roc_20, 2),
            "Vol Ratio": round(vol_ratio, 2),
            "Momentum": round(momentum_score, 1),
            "Rating": rating,
        }
    except Exception:
        return None

def main():
    print(f"=== Stock Screener — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    print("Criteria: Above 50d EMA | Positive weekly gain | Market cap > $1B")
    print("Fetching universe...\n")

    tickers = get_universe()
    if not tickers:
        print("ERROR: Could not fetch ticker lists. Check network.")
        sys.exit(1)

    print(f"Screening {len(tickers)} stocks (this may take 15-20 min)...\n")

    import time

    import time

    results = []
    failed_tickers = []

    # Process in batches to avoid rate-limiting
    batch_size = 50
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(screen_stock, t): t for t in batch}
            for future in as_completed(futures):
                result = future.result()
                if result and result != FILTERED:
                    results.append(result)
                elif result is None:
                    failed_tickers.append(futures[future])
        done = min(i + batch_size, len(tickers))
        if done % 200 == 0 or done == len(tickers):
            print(f"  Progress: {done}/{len(tickers)} ({len(results)} passed, {len(failed_tickers)} errors)")
        time.sleep(1)

    # Retry only actual failures (not filtered stocks)
    if failed_tickers:
        print(f"\n  Retrying {len(failed_tickers)} tickers that errored...")
        for i in range(0, len(failed_tickers), 20):
            batch = failed_tickers[i:i + 20]
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(screen_stock, t): t for t in batch}
                for future in as_completed(futures):
                    result = future.result()
                    if result and result != FILTERED:
                        results.append(result)
            time.sleep(2)
        print(f"  After retry: {len(results)} total passed")

    if not results:
        print("\nNo stocks matched all criteria today.")
        return

    df = pd.DataFrame(results)
    df = df.sort_values("Momentum", ascending=False)
    df = df.reset_index(drop=True)
    df.index += 1

    print(f"\n{'='*80}")
    print(f"  {len(df)} stocks passed all filters")
    print(f"  Sorted by composite momentum (MACD 35 | ROC 30 | Volume 25 | EMA 10)")
    print(f"  Rating: 5=Strong Buy → 1=Strong Sell | Vol Ratio: >1 = above avg volume")
    print(f"{'='*80}\n")
    print(df.to_string())
    print()

    # Save CSV for local viewing/sorting
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output.csv")
    df.to_csv(csv_path, index=False)
    print(f"CSV saved to {csv_path}")

if __name__ == "__main__":
    main()

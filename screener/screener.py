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

def get_sp500():
    """Fetch S&P 500 constituents from GitHub (reliable, no auth needed)."""
    try:
        from io import StringIO
        resp = requests.get(
            "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
            timeout=10
        )
        if resp.status_code == 200:
            import pandas as pd
            df = pd.read_csv(StringIO(resp.text))
            tickers = set(df["Symbol"].str.replace(".", "-", regex=False).tolist())
            print(f"  S&P 500 loaded: {len(tickers)} tickers")
            return tickers
    except Exception:
        pass
    return set()


def get_universe():
    """Fetch all US-traded stocks with market cap > $1B from NASDAQ screener, sorted by daily gain.

    Returns (tickers_sorted_by_daily_gain, {ticker: marketCap}). The marketCap
    comes straight from NASDAQ so we can filter without a yfinance .info call.
    """
    url = "https://api.nasdaq.com/api/screener/stocks?tableType=traded&limit=10000&offset=0"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        data = resp.json()
        rows = data["data"]["table"]["rows"]
        candidates = []
        mcap_map = {}
        for r in rows:
            mcap_str = r.get("marketCap", "0").replace(",", "").replace(" ", "")
            try:
                mcap = int(float(mcap_str))
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
                    mcap_map[symbol] = mcap
        # Sort by daily gain descending — top movers get processed first
        candidates.sort(key=lambda x: x[1], reverse=True)
        tickers = [c[0] for c in candidates]
        print(f"  NASDAQ screener: {len(tickers)} stocks with market cap > $1B")
        print(f"  Top 5 by daily gain: {', '.join(f'{c[0]}({c[1]:+.1f}%)' for c in candidates[:5])}")
        return tickers, mcap_map
    except Exception as e:
        print(f"  ERROR fetching universe: {e}")
        return [], {}

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


def screen_from_history(ticker, hist, market_cap):
    """Screen a single ticker from already-downloaded price history + known market cap.

    Returns a result dict if it passes all filters, FILTERED if it legitimately
    fails a filter, or None if the history is missing/insufficient (retry candidate).
    """
    try:
        if hist is None or hist.empty or len(hist) < 50:
            return None  # no/short data — retry candidate

        close = hist["Close"].dropna()
        if len(close) < 50:
            return None

        current_price = float(close.iloc[-1])
        prev_close = float(close.iloc[-2]) if len(close) >= 2 else current_price
        daily_move = (current_price - prev_close) / prev_close * 100 if prev_close else 0

        # Market cap filter (from NASDAQ data)
        if not market_cap or market_cap < 1_000_000_000:
            return FILTERED

        # 50-day EMA filter — must be above
        ema_50 = compute_ema(close, span=50)
        current_ema = float(ema_50.iloc[-1])
        if current_price <= current_ema:
            return FILTERED

        # Positive weekly gain
        five_days_ago = float(close.iloc[-6]) if len(close) >= 6 else float(close.iloc[0])
        weekly_gain = (current_price - five_days_ago) / five_days_ago * 100 if five_days_ago else 0
        if weekly_gain <= 0:
            return FILTERED

        # Momentum signals
        rsi = float(compute_rsi(close).iloc[-1])
        macd_line, signal_line, macd_hist = compute_macd(close)
        macd_val = float(macd_line.iloc[-1])
        macd_signal = float(signal_line.iloc[-1])
        macd_histogram = float(macd_hist.iloc[-1])

        roc_20 = (current_price - float(close.iloc[-21])) / float(close.iloc[-21]) * 100 if len(close) >= 21 else 0

        vol = hist["Volume"].dropna()
        vol_avg_20 = float(vol.iloc[-20:].mean()) if len(vol) >= 20 else float(vol.mean())
        vol_ratio = float(vol.iloc[-1]) / vol_avg_20 if vol_avg_20 > 0 else 1.0

        ema_spread = (current_price - current_ema) / current_ema * 100
        momentum_score = (
            (min(max(macd_histogram / current_price * 1000, 0), 5) / 5) * 35 +
            (min(max(roc_20, 0), 30) / 30) * 30 +
            (min(max(vol_ratio, 0), 3) / 3) * 25 +
            (min(max(ema_spread, 0), 20) / 20) * 10
        )

        return {
            "Ticker": ticker,
            "Price": round(current_price, 2),
            "Day%": round(daily_move, 2),
            "Week%": round(weekly_gain, 2),
            "MCap($B)": round(market_cap / 1e9, 1),
            "Sector": "N/A",     # enriched later for passers only
            "Industry": "N/A",
            "Above EMA%": round(ema_spread, 2),
            "RSI": round(rsi, 1),
            "MACD": "Bull" if macd_val > macd_signal else "Bear",
            "MACD Hist": round(macd_histogram, 2),
            "ROC20%": round(roc_20, 2),
            "Vol Ratio": round(vol_ratio, 2),
            "Momentum": round(momentum_score, 1),
            "Rating": None,      # enriched later for passers only
        }
    except Exception:
        return None


def download_batch(tickers, retries=2):
    """Batch-download 6mo daily history for a list of tickers in one HTTP call.

    Returns {ticker: DataFrame}. yf.download with group_by='ticker' returns a
    multi-index frame; we split it back per ticker. Retries the whole batch on
    transient failures.
    """
    import pandas as pd
    out = {}
    if not tickers:
        return out
    for attempt in range(retries + 1):
        try:
            data = yf.download(
                tickers=" ".join(tickers),
                period="6mo",
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )
            if data is None or data.empty:
                continue
            # Single ticker -> flat columns; multi -> top-level ticker columns
            if len(tickers) == 1:
                out[tickers[0]] = data.dropna(how="all")
            else:
                for t in tickers:
                    if t in data.columns.get_level_values(0):
                        df = data[t].dropna(how="all")
                        if not df.empty:
                            out[t] = df
            if out:
                return out
        except Exception:
            pass
    return out

def enrich_one(result):
    """Fetch sector/industry/rating for a single passing ticker."""
    try:
        info = yf.Ticker(result["Ticker"]).info
        result["Sector"] = info.get("sector", "N/A")
        result["Industry"] = info.get("industry", "N/A")
        raw = info.get("recommendationMean", None)
        result["Rating"] = round(6 - raw, 2) if raw else None
    except Exception:
        pass
    return result


def enrich_passers(results):
    """Enrich passing results with sector/rating info, in parallel.

    Each enrich_one() is a slow per-ticker yfinance .info scrape. On a heavy day
    1000+ stocks pass, and enriching all of them adds ~5 min to the run (pushing
    the email past 10 AM) for data the brief/email never surface beyond the top
    movers. Callers pass only the top-N slice they actually display.
    """
    import time
    batch = 20
    for i in range(0, len(results), batch):
        chunk = results[i:i + batch]
        with ThreadPoolExecutor(max_workers=16) as ex:
            list(ex.map(enrich_one, chunk))
        time.sleep(0.3)


def main():
    print(f"=== Stock Screener — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    print("Criteria: Above 50d EMA | Positive weekly gain | Market cap > $1B")
    print("Fetching universe...\n")

    tickers, mcap_map = get_universe()
    if not tickers:
        print("ERROR: Could not fetch ticker lists. Check network.")
        sys.exit(1)

    import time

    # Merge S&P 500 into the universe so large-caps are always screened, even if
    # they haven't moved yet (NASDAQ sorts by daily gain). All tickers are now
    # processed via cheap batched downloads, so there's no priority/remaining split.
    sp500 = get_sp500()
    universe_set = set(tickers)
    # S&P 500 members might not be in the NASDAQ list; add them (mcap unknown -> use large default)
    for t in sp500:
        if t not in universe_set:
            tickers.append(t)
            mcap_map.setdefault(t, 5_000_000_000)  # S&P 500 members are all > $1B
            universe_set.add(t)

    print(f"Screening {len(tickers)} stocks via batched downloads...\n")

    results = []
    failed = []

    # Batch-download price history — 50 tickers per HTTP request.
    BATCH = 50
    total = len(tickers)
    for i in range(0, total, BATCH):
        batch = tickers[i:i + BATCH]
        hist_map = download_batch(batch)
        for t in batch:
            res = screen_from_history(t, hist_map.get(t), mcap_map.get(t, 0))
            if res and res != FILTERED:
                results.append(res)
            elif res is None:
                failed.append(t)
        done = min(i + BATCH, total)
        if done % 200 == 0 or done == total:
            print(f"  Screened {done}/{total} ({len(results)} passed, {len(failed)} no-data)")
        time.sleep(0.5)

    # Retry tickers with no data (smaller batches)
    if failed:
        print(f"\n  Retrying {len(failed)} tickers with no data...")
        retry = failed[:]
        for i in range(0, len(retry), 25):
            batch = retry[i:i + 25]
            hist_map = download_batch(batch)
            for t in batch:
                res = screen_from_history(t, hist_map.get(t), mcap_map.get(t, 0))
                if res and res != FILTERED:
                    results.append(res)
            time.sleep(0.5)
        print(f"  After retry: {len(results)} passed")

    print(f"\n  Final: {len(results)} stocks passed all filters")

    if not results:
        print("\nNo stocks matched all criteria today.")
        return

    # Enrich only the rows the brief/email/blog actually surface, using the slow
    # per-ticker .info scrape. Enriching all 1000+ passers added ~5 min and pushed
    # the email past 10 AM. We enrich the union of (top by momentum) and (top by
    # daily gain) — the latter because the news brief pulls top daily movers, which
    # aren't always high-momentum. Remaining rows keep Sector="N/A"/Rating=None.
    ENRICH_TOP_MOMENTUM = 150
    ENRICH_TOP_MOVERS = 30
    by_momentum = sorted(results, key=lambda r: r["Momentum"], reverse=True)[:ENRICH_TOP_MOMENTUM]
    by_move = sorted(results, key=lambda r: r["Day%"], reverse=True)[:ENRICH_TOP_MOVERS]
    seen = set()
    top = []
    for r in by_momentum + by_move:
        if r["Ticker"] not in seen:
            seen.add(r["Ticker"])
            top.append(r)
    print(f"\n  Enriching {len(top)} of {len(results)} passers with sector/rating "
          f"(top {ENRICH_TOP_MOMENTUM} momentum + top {ENRICH_TOP_MOVERS} movers)...")
    enrich_passers(top)

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

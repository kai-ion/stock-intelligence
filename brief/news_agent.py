#!/usr/bin/env python3
"""
Fetch news for top 20 daily movers, summarize with Claude via Bedrock,
and append to the morning email.
"""

import boto3
import json
import yfinance as yf
import os
from datetime import datetime

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-opus-4-6-v1")
OUTPUT_FILE = "/home/ec2-user/output.log"
NEWS_FILE = "/home/ec2-user/news.log"


def get_top_movers(n=20):
    """Parse screener output and return top N by daily gain with full data."""
    if not os.path.exists(OUTPUT_FILE):
        return []

    with open(OUTPUT_FILE) as f:
        lines = f.readlines()

    header_idx = None
    for i, line in enumerate(lines):
        if "Ticker" in line and "Price" in line and "Day%" in line:
            header_idx = i
            break
    if header_idx is None:
        return []

    # Parse header to find column positions
    header = lines[header_idx]
    headers = header.split()

    stocks = []
    for line in lines[header_idx + 1:]:
        parts = line.split()
        if len(parts) < 10:
            continue
        try:
            # Row number is first, then data fields
            # Use known positions: Ticker is always parts[1], then Price, Day%, Week%
            ticker = parts[1]
            price = float(parts[2])
            day_pct = float(parts[3])
            week_pct = float(parts[4])

            # Find RSI, Vol Ratio, Momentum from end (they're always numeric from the right)
            # Work backwards: last field could be Sector (text) or Rating (numeric)
            # Find the rightmost numeric fields
            numeric_from_end = []
            for p in reversed(parts):
                try:
                    numeric_from_end.append(float(p))
                except ValueError:
                    if p in ("Bull", "Bear"):
                        numeric_from_end.append(p)
                    else:
                        break

            # Typical order from right: Sector(text) MCap Rating Momentum VolRatio ROC20 MACDHist MACD RSI AboveEMA
            # Or new order: Rating Momentum VolRatio ROC20 MACDHist MACD RSI AboveEMA ... Sector Industry MCap
            # Just grab what we can reliably
            rsi = 50.0
            vol_ratio = 1.0
            momentum = 50.0
            roc20 = 0.0
            rating = "N/A"

            # Find specific values by header position if possible
            if "RSI" in headers:
                rsi_idx = headers.index("RSI")
                # Account for row index offset
                try:
                    rsi = float(parts[rsi_idx + 1])
                except (ValueError, IndexError):
                    pass

            stocks.append({
                "ticker": ticker,
                "price": price,
                "day_pct": day_pct,
                "week_pct": week_pct,
                "rsi": rsi,
                "vol_ratio": vol_ratio,
                "momentum": momentum,
            })
        except (IndexError, ValueError):
            continue

    stocks.sort(key=lambda x: x["day_pct"], reverse=True)
    return stocks[:n]


def fetch_technicals(tickers):
    """Compute key technical levels for each ticker: fib retracements, support/resistance."""
    technicals = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="6mo")
            if hist.empty or len(hist) < 20:
                continue

            close = hist["Close"]
            current = float(close.iloc[-1])
            high_6mo = float(close.max())
            low_6mo = float(close.min())

            # Fibonacci retracement levels (from 6mo low to high)
            fib_range = high_6mo - low_6mo
            fib_236 = high_6mo - fib_range * 0.236
            fib_382 = high_6mo - fib_range * 0.382
            fib_500 = high_6mo - fib_range * 0.500
            fib_618 = high_6mo - fib_range * 0.618

            # Fibonacci extension levels (from low, projecting above high)
            fib_ext_1272 = low_6mo + fib_range * 1.272
            fib_ext_1618 = low_6mo + fib_range * 1.618

            # Recent support/resistance (20-day high/low)
            high_20d = float(close.iloc[-20:].max())
            low_20d = float(close.iloc[-20:].min())

            # 50-day and 200-day moving averages
            sma_50 = float(close.iloc[-50:].mean()) if len(close) >= 50 else None
            sma_200 = float(close.iloc[-200:].mean()) if len(close) >= 200 else None

            # Volume profile: average volume
            avg_vol = float(hist["Volume"].iloc[-20:].mean())
            today_vol = float(hist["Volume"].iloc[-1])

            technicals[ticker] = {
                "current_price": round(current, 2),
                "6mo_high": round(high_6mo, 2),
                "6mo_low": round(low_6mo, 2),
                "20d_high": round(high_20d, 2),
                "20d_low": round(low_20d, 2),
                "fib_236_support": round(fib_236, 2),
                "fib_382_support": round(fib_382, 2),
                "fib_500_support": round(fib_500, 2),
                "fib_618_support": round(fib_618, 2),
                "fib_ext_1.272": round(fib_ext_1272, 2),
                "fib_ext_1.618": round(fib_ext_1618, 2),
                "sma_50": round(sma_50, 2) if sma_50 else None,
                "sma_200": round(sma_200, 2) if sma_200 else None,
                "vol_vs_avg": round(today_vol / avg_vol, 2) if avg_vol > 0 else 1.0,
            }
        except Exception:
            continue
    return technicals


def fetch_news(tickers):
    """Fetch news for each ticker via yfinance."""
    all_news = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            news = stock.news
            headlines = []
            for item in news[:5]:
                content = item.get("content", {})
                title = content.get("title", "")
                summary = content.get("summary", "")
                pub_date = content.get("pubDate", "")
                if title:
                    headlines.append({"title": title, "summary": summary, "date": pub_date})
            all_news[ticker] = headlines
        except Exception:
            all_news[ticker] = []
    return all_news


def fetch_market_headlines():
    """Fetch general market news."""
    try:
        spy = yf.Ticker("SPY")
        news = spy.news
        headlines = []
        for item in news[:10]:
            content = item.get("content", {})
            title = content.get("title", "")
            summary = content.get("summary", "")
            if title:
                headlines.append({"title": title, "summary": summary})
        return headlines
    except Exception:
        return []


def fetch_earnings_reactions():
    """Check recent earnings from weekly report tickers — what beat/missed and price reaction."""
    from datetime import timedelta
    from pathlib import Path
    import re as re_mod

    # Find the current week's events report
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    week_file = Path(OUTPUT_FILE).parent / f"events/data/week_{monday.strftime('%Y-%m-%d')}.md"

    # Also check S3 synced location on EC2
    alt_paths = [
        Path(f"/home/ec2-user/events/data/week_{monday.strftime('%Y-%m-%d')}.md"),
        Path(f"/home/ec2-user/repo/events/{monday.strftime('%Y-%m')}/week_{monday.strftime('%Y-%m-%d')}.md"),
    ]

    report_content = ""
    for path in [week_file] + alt_paths:
        if path.exists():
            report_content = path.read_text()
            break

    if not report_content:
        return []

    # Extract tickers from the weekly report
    ticker_pattern = re_mod.compile(r'\*\*([A-Z]{1,5})\*\*\s*—.*?Reports:', re_mod.DOTALL)
    weekly_tickers = list(set(ticker_pattern.findall(report_content)))

    if not weekly_tickers:
        # Fallback: grab all tickers mentioned in the calendar section
        cal_pattern = re_mod.compile(r'\(([A-Z]{1,5})\)')
        weekly_tickers = list(set(cal_pattern.findall(report_content)))

    # Filter to tickers that reported yesterday or today (by checking which day in the weekly report)
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)
    three_days_ago = today - timedelta(days=3)
    # Include today (Before Open reports), yesterday, and 2-3 days ago
    target_days = [today.strftime("%A"), yesterday.strftime("%A"), two_days_ago.strftime("%A"), three_days_ago.strftime("%A")]
    # Deduplicate (in case of weekends)
    target_days = list(dict.fromkeys(target_days))

    # Find tickers that were scheduled for yesterday/day-before, with their day + timing
    scheduled_tickers = []
    ticker_report_day = {}  # ticker -> "Tuesday Before Open" etc.
    for day_name in target_days:
        day_pattern = re_mod.compile(
            rf'###\s*{day_name}.*?(?=###|\Z)',
            re_mod.DOTALL | re_mod.IGNORECASE
        )
        day_match = day_pattern.search(report_content)
        if day_match:
            section = day_match.group(0)
            tickers_in_section = re_mod.findall(r'\*\*([A-Z]{1,5})\*\*', section)
            for t in tickers_in_section:
                scheduled_tickers.append(t)
                # Try to find timing (Before Open / After Close)
                timing_match = re_mod.search(rf'\*\*{t}\*\*.*?\((Before Open|After Close|TBD)\)', section)
                timing = timing_match.group(1) if timing_match else ""
                ticker_report_day[t] = f"{day_name} {timing}".strip()

    # Also include any tickers from the full weekly list as fallback
    if not scheduled_tickers:
        scheduled_tickers = weekly_tickers

    # Deduplicate
    scheduled_tickers = list(dict.fromkeys(scheduled_tickers))

    print(f"    Scheduled tickers ({len(scheduled_tickers)}): {', '.join(scheduled_tickers[:15])}")

    # Get price reactions for all scheduled tickers
    reactions = []
    for ticker in scheduled_tickers[:25]:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            hist = stock.history(period="5d")

            if hist.empty or len(hist) < 2:
                continue

            mcap = info.get("marketCap", 0)
            if not mcap or mcap < 5_000_000_000:
                continue

            # Get price reaction (today vs yesterday)
            prev_close = float(hist["Close"].iloc[-2])
            current = float(hist["Close"].iloc[-1])
            reaction_pct = (current - prev_close) / prev_close * 100

            # Get EPS data
            trailing_eps = info.get("trailingEps", None)
            cal = stock.calendar
            eps_estimate = cal.get("Earnings Average", None) if cal else None

            beat_miss = "REPORTED"
            surprise_pct = ""
            if eps_estimate and trailing_eps:
                diff = trailing_eps - eps_estimate
                surprise_pct = f"{(diff / abs(eps_estimate)) * 100:.1f}%" if eps_estimate != 0 else ""
                beat_miss = "BEAT" if diff > 0 else "MISS"

            reactions.append({
                "ticker": ticker,
                "name": info.get("shortName", ticker),
                "reported": ticker_report_day.get(ticker, ""),
                "eps_estimate": f"${eps_estimate:.2f}" if eps_estimate else "N/A",
                "eps_actual": f"${trailing_eps:.2f}" if trailing_eps else "N/A",
                "surprise": surprise_pct,
                "reaction_pct": round(reaction_pct, 2),
                "beat_miss": beat_miss,
            })
        except Exception:
            continue

    reactions.sort(key=lambda x: abs(x.get("reaction_pct", 0)), reverse=True)
    print(f"    Found {len(reactions)} earnings reactions")
    return reactions[:15]


def summarize_with_claude(top_movers, ticker_news, market_headlines, technicals, wsb_trending=None, earnings_reactions=None, comps_data=None):
    """Use Claude via Bedrock to create a morning brief."""
    from botocore.config import Config
    config = Config(read_timeout=300)
    bedrock = boto3.client("bedrock-runtime", region_name=REGION, config=config)

    # Load analyst expertise
    from analyst_prompts import EARNINGS_ANALYST_CONTEXT, COMPS_ANALYST_CONTEXT, MARKET_RESEARCHER_CONTEXT

    wsb_section = ""
    if wsb_trending:
        wsb_section = f"""

WALLSTREETBETS TRENDING TICKERS (top 5 by mentions/engagement):
{json.dumps(wsb_trending, indent=2)}
"""

    earnings_section = ""
    if earnings_reactions:
        earnings_section = f"""

YESTERDAY'S EARNINGS REACTIONS (stocks that reported in the last 1-2 days):
{json.dumps(earnings_reactions, indent=2)}
"""

    comps_section = ""
    if comps_data:
        comps_section = f"""

VALUATION COMPS (forward P/E and EV/EBITDA vs peer medians — use for picks):
{json.dumps(comps_data, indent=2)}
"""

    prompt = f"""You are a technical stock market analyst preparing a morning brief. Today is {datetime.now().strftime('%Y-%m-%d')}.

ANALYST EXPERTISE:
{EARNINGS_ANALYST_CONTEXT}
{COMPS_ANALYST_CONTEXT}
{MARKET_RESEARCHER_CONTEXT}

TOP 20 STOCKS BY DAILY GAIN:
{json.dumps(top_movers, indent=2)}

TECHNICAL LEVELS PER TICKER (fib retracements from 6mo swing, support/resistance, MAs):
{json.dumps(technicals, indent=2)}

NEWS PER TICKER:
{json.dumps(ticker_news, indent=2)}

GENERAL MARKET HEADLINES:
{json.dumps(market_headlines, indent=2)}
{wsb_section}{earnings_section}{comps_section}

Create a concise morning brief in this exact format:

## Market Overview
2-3 sentences on what's driving the market today.

## Top Movers

For each stock, use this exact format:

**TICKER** (+X.X%) — $CURRENT_PRICE → $EXIT_TARGET (+Y.Y% upside)
Thesis: 1-2 sentences combining the fundamental catalyst with the technical setup. Explain WHY this stock is moving (earnings, deal, upgrade, sector rotation) AND where it sits technically (breakout, extension, pullback bounce). This should read like a quick pitch — why someone should care about this name today.
Levels: Exit at [specific fib/resistance level with price]. Support at [specific fib/SMA level with price].

Keep the thesis conversational and opinionated — share your genuine take on whether this move has legs or is a trap. Call out weak catalysts (e.g., "Trump pump — historically these fade within 48 hours", "sector sympathy with no company-specific news is the weakest reason to buy"). Be the smart friend who tells it straight, not a news ticker.

Reference technical levels where they strengthen the argument (e.g., "broke above 6mo resistance on 2x volume" or "already past fib 1.618 — chasing here is dangerous").

Use the technical data to set exit targets (fib extensions, prior highs, SMAs) and support levels (fib retracements, SMAs, 20d lows). If a stock is past fib 1.618 extension, flag it as overextended.

## Headlines to Watch

5-7 bullets, each formatted as:
- **Headline title** — One sentence on why it matters for your portfolio.

## Claude's Top Picks

From the 20 stocks above, pick the 3-5 you would buy TODAY for a short-term swing trade (1-2 week hold). For each pick use this exact format:

**TICKER** (+X.X% today, +Y.Y% week) — $CURRENT → $EXIT_TARGET (+Z.Z% upside)
Valuation: One sentence on whether it's cheap or expensive vs peers (use the comps data if available).
Upside: One sentence on why this has room to run.
Risk: One sentence on what could go wrong.

Then end with:

## Avoid

List 2-3 stocks from the top 20 that look extended or risky to chase, with one sentence why.

## WSB Sentiment Check

For each of the 5 WSB trending tickers, give your honest take:

**TICKER** — WSB says: BULLISH/BEARISH/MIXED (X% bullish)
Claude says: AGREE/DISAGREE/PARTIALLY — One sentence. Do the technicals support WSB's thesis or are they delusional? Reference the actual chart setup. If it's a short squeeze play, say whether the setup is real or hopium. Be blunt — WSB is often wrong at extremes.

## Earnings Scorecard

If yesterday's earnings reactions data is provided, create a brief scorecard. For each stock that reported:

**TICKER** — BEAT/MISS by X% | Stock: +/-Y.Y% | Reported: [Day] [Before Open/After Close]
One sentence: Was the reaction justified? Did the market over/under-react? Is this now a buy-the-dip or sell-the-rip?

If no earnings data is provided, skip this section entirely.

Selection criteria you must weigh:
- Catalyst strength (real news > sector sympathy)
- Technical setup (price near fib support = good entry; price past fib 1.618 extension = overextended)
- Volume confirmation (high vol ratio = conviction)
- Risk/reward — prefer stocks with clear support nearby and resistance room above

Rules:
- Reference specific technical levels in your reasoning (fib levels, SMAs, prior highs/lows)
- Be specific about catalysts (earnings beat, upgrade, deal announced) not vague ("momentum")
- If no news explains the move, say "Sector sympathy" or "Technical breakout" — don't make up catalysts
- For picks, include the nearest support level as a stop-loss reference
- For avoid, reference how far past key fib extensions the stock is
- Keep Upside and Risk as separate lines, not combined into one paragraph"""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 7000,
        "messages": [{"role": "user", "content": prompt}]
    })

    response = bedrock.invoke_model(modelId=MODEL_ID, body=body)
    result = json.loads(response["body"].read())
    return result["content"][0]["text"]


def main():
    print("Fetching top 20 daily movers...")
    top_movers = get_top_movers(20)
    if not top_movers:
        print("No movers found")
        return

    tickers = [t["ticker"] for t in top_movers]
    print(f"Top movers: {', '.join(tickers)}")

    print("Fetching technicals...")
    technicals = fetch_technicals(tickers)

    print("Fetching news...")
    ticker_news = fetch_news(tickers)
    market_headlines = fetch_market_headlines()

    print("Fetching WSB sentiment...")
    from wsb_sentiment import get_wsb_trending
    wsb_trending = get_wsb_trending(5)

    # If direct scrape failed (Reddit blocks EC2), try S3 cache from local sync
    if not wsb_trending:
        try:
            import boto3 as _boto3
            _s3 = _boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
            _resp = _s3.get_object(Bucket=os.environ.get("S3_BUCKET", ""), Key="wsb/latest.json")
            wsb_trending = json.loads(_resp["Body"].read())
            print("  Loaded WSB data from S3 cache")
        except Exception:
            pass

    print(f"WSB trending: {', '.join(t['ticker'] for t in wsb_trending) if wsb_trending else 'NONE'}")

    # Fetch technicals for WSB tickers not already covered
    wsb_tickers = [t["ticker"] for t in wsb_trending]
    for t in wsb_tickers:
        if t not in technicals:
            tech = fetch_technicals([t])
            if t in tech:
                technicals[t] = tech[t]

    print("Fetching earnings reactions...")
    earnings_reactions = fetch_earnings_reactions()
    print(f"  {len(earnings_reactions)} earnings to review")

    print("Fetching comps data for top movers...")
    from financial_skills import get_comps_data, get_earnings_transcript_summary
    comps_data = {}
    for t in tickers[:10]:
        comps = get_comps_data(t)
        if comps:
            comps_data[t] = {
                "valuation_vs_peers": comps["valuation_vs_peers"],
                "pe_forward": comps["target"]["pe_forward"] if comps["target"] else None,
                "peer_median_pe": comps["peer_medians"]["pe_forward"],
                "ev_ebitda": comps["target"]["ev_ebitda"] if comps["target"] else None,
                "peer_median_ev_ebitda": comps["peer_medians"]["ev_ebitda"],
                "revenue_growth": comps["target"]["revenue_growth"] if comps["target"] else None,
            }
    print(f"  Comps for {len(comps_data)} tickers")

    # Enrich earnings reactions with transcript summaries
    for reaction in earnings_reactions:
        transcript = get_earnings_transcript_summary(reaction["ticker"])
        if transcript and transcript.get("earnings_news"):
            reaction["key_headlines"] = [n["title"] for n in transcript["earnings_news"][:3]]
            reaction["analyst_target"] = transcript["financials"].get("analyst_target")

    print("Summarizing with Claude...")
    brief = summarize_with_claude(top_movers, ticker_news, market_headlines, technicals, wsb_trending, earnings_reactions, comps_data)

    with open(NEWS_FILE, "w") as f:
        f.write(brief)

    print(f"Morning brief saved to {NEWS_FILE}")
    print(brief)


if __name__ == "__main__":
    main()

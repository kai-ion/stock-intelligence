#!/usr/bin/env python3
"""
Analyze Robinhood portfolio: compute technical levels, exit targets, and generate
a morning brief with Claude via Bedrock.
"""

import json
import os
import sys
import boto3
import yfinance as yf
from datetime import datetime
from pathlib import Path
from botocore.config import Config

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-opus-4-6-v1")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
DATA_DIR = Path(__file__).parent / "data"


def load_holdings():
    """Load today's portfolio data, falling back to most recent if today's fetch failed."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = DATA_DIR / f"{date_str}.json"

    if path.exists():
        with open(path) as f:
            data = json.load(f)
            data["_stale"] = False
            return data

    # Fallback: find the most recent portfolio file
    all_files = sorted(DATA_DIR.glob("*.json"), reverse=True)
    # Filter to actual portfolio files (not analysis)
    portfolio_files = [f for f in all_files if "_analysis" not in f.name]
    if portfolio_files:
        latest = portfolio_files[0]
        print(f"WARNING: No portfolio data for today. Using {latest.name} (stale data).")
        with open(latest) as f:
            data = json.load(f)
            data["_stale"] = True
            data["_stale_date"] = latest.stem
            return data

    print("ERROR: No portfolio data found at all.")
    sys.exit(1)


def fetch_technicals(ticker):
    """Compute fib levels, support/resistance, and MAs for a single ticker."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        if hist.empty or len(hist) < 20:
            return None

        close = hist["Close"]
        current = float(close.iloc[-1])
        high_6mo = float(close.max())
        low_6mo = float(close.min())

        fib_range = high_6mo - low_6mo
        fib_236 = high_6mo - fib_range * 0.236
        fib_382 = high_6mo - fib_range * 0.382
        fib_500 = high_6mo - fib_range * 0.500
        fib_618 = high_6mo - fib_range * 0.618
        fib_ext_1272 = low_6mo + fib_range * 1.272
        fib_ext_1618 = low_6mo + fib_range * 1.618

        high_20d = float(close.iloc[-20:].max())
        low_20d = float(close.iloc[-20:].min())

        sma_50 = float(close.iloc[-50:].mean()) if len(close) >= 50 else None
        sma_200 = float(close.iloc[-200:].mean()) if len(close) >= 200 else None

        # EMA 50
        ema_50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])

        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/14, min_periods=14).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14).mean()
        rs = avg_gain / avg_loss
        rsi = float((100 - (100 / (1 + rs))).iloc[-1])

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = float((macd_line - signal_line).iloc[-1])

        # Volume
        vol = hist["Volume"]
        vol_avg = float(vol.iloc[-20:].mean())
        vol_today = float(vol.iloc[-1])

        return {
            "current_price": round(current, 2),
            "6mo_high": round(high_6mo, 2),
            "6mo_low": round(low_6mo, 2),
            "20d_high": round(high_20d, 2),
            "20d_low": round(low_20d, 2),
            "ema_50": round(ema_50, 2),
            "sma_50": round(sma_50, 2) if sma_50 else None,
            "sma_200": round(sma_200, 2) if sma_200 else None,
            "rsi": round(rsi, 1),
            "macd_histogram": round(macd_hist, 2),
            "fib_236_support": round(fib_236, 2),
            "fib_382_support": round(fib_382, 2),
            "fib_500_support": round(fib_500, 2),
            "fib_618_support": round(fib_618, 2),
            "fib_ext_1.272": round(fib_ext_1272, 2),
            "fib_ext_1.618": round(fib_ext_1618, 2),
            "vol_vs_avg": round(vol_today / vol_avg, 2) if vol_avg > 0 else 1.0,
        }
    except Exception as e:
        print(f"  Warning: technicals failed for {ticker}: {e}")
        return None


def analyze_with_claude(holdings_data, technicals):
    """Send portfolio + technicals to Claude for exit analysis."""
    config = Config(read_timeout=300)
    bedrock = boto3.client("bedrock-runtime", region_name=REGION, config=config)

    # Load analyst expertise
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from analyst_prompts import PORTFOLIO_ANALYST_CONTEXT, COMPS_ANALYST_CONTEXT
    except ImportError:
        PORTFOLIO_ANALYST_CONTEXT = ""
        COMPS_ANALYST_CONTEXT = ""

    # Flag earnings tickers in prompt
    earnings_tickers = [h["ticker"] for h in holdings_data if h.get("earnings_today")]
    earnings_warning = ""
    if earnings_tickers:
        earnings_warning = f"\n⚡ THESE TICKERS REPORT EARNINGS TODAY: {', '.join(earnings_tickers)}. For each, note the earnings risk and whether to hold through or trim before the print.\n"

    prompt = f"""You are a technical analyst reviewing a personal stock portfolio. Today is {datetime.now().strftime('%Y-%m-%d')}.

ANALYST EXPERTISE:
{PORTFOLIO_ANALYST_CONTEXT}
{COMPS_ANALYST_CONTEXT}
{earnings_warning}
PORTFOLIO HOLDINGS (earnings_today=true means that ticker reports earnings today):
{json.dumps(holdings_data, indent=2)}

TECHNICAL LEVELS PER HOLDING (fib retracements from 6mo swing, support/resistance, MAs, RSI, MACD):
{json.dumps(technicals, indent=2)}

Structure the output in this EXACT order:

## Sell / Trim (action required)

List positions with status TRIM or EXIT FIRST. These are the most urgent. For each:

**TICKER** — {"{"}shares{"}"} shares @ ${"{"}avg_cost{"}"} → Current ${"{"}price{"}"} ({"{"}P&L %{"}"})
Action: TRIM X% or EXIT — one sentence why (reference RSI, extension level, or broken thesis).
Exit Target: $X.XX (+Y.Y%) — specific technical level.
Stop Loss: $X.XX (-Z.Z%) — specific support level.

## Add More

List positions with status ADD — stocks you already own that deserve more capital. For each:

**TICKER** — Current ${"{"}price{"}"}
Add at: $X.XX — the price level to add (pullback to fib support, SMA, or 20d low).
Why: One sentence on why this position deserves more capital (strong setup, undersized, catalyst ahead).
Target after add: $X.XX — where the position goes from the add level.

## Hold (no action)

List positions with status HOLD. Keep these brief — one line each:

**TICKER** — ${"{"}price{"}"} ({"{"}P&L %{"}"}) — HOLD. One sentence thesis. Exit at $X.XX, stop at $X.XX.

## Stocks to Buy (not currently held)

Based on the portfolio's sector exposure and technical setups, suggest 2-3 stocks NOT in the portfolio that would complement it. For each:

**TICKER** — Current $X.XX
Why buy: One sentence on the thesis — what gap does this fill in the portfolio (missing sector, strong breakout, underrepresented theme).
Entry: $X.XX (specific level to buy at).
Target: $X.XX (+Y.Y% upside).

Consider: AI infrastructure names the user doesn't own yet, sectors that are underweight (healthcare, energy transition, defense), or high-conviction breakouts from the screener universe.

---

Rules:
- SELL/TRIM section comes FIRST — these are time-sensitive
- Exit targets must reference fib extensions, prior highs, or analyst targets
- Stop losses must reference fib retracements, SMAs, or 20d lows
- TRIM means partial profits (specify how much: 25%, 33%, 50%)
- EXIT means close entirely
- ADD means buy more shares at a specific price level
- For "Stocks to Buy" — only suggest names with strong technical setups (above EMA, bullish MACD, not overbought)
- Be opinionated and direct. No hedging."""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 6000,
        "messages": [{"role": "user", "content": prompt}]
    })

    response = bedrock.invoke_model(modelId=MODEL_ID, body=body)
    result = json.loads(response["body"].read())
    return result["content"][0]["text"]


def get_tickers_reporting_today():
    """Check the weekly events report for tickers reporting earnings today."""
    from datetime import timedelta
    import re as re_mod

    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    day_name = today.strftime("%A")

    # Find the weekly report
    report_paths = [
        Path(f"/home/ec2-user/events/data/week_{monday.strftime('%Y-%m-%d')}.md"),
        Path(f"/home/ec2-user/repo/events/{monday.strftime('%Y-%m')}/week_{monday.strftime('%Y-%m-%d')}.md"),
    ]

    for path in report_paths:
        if path.exists():
            content = path.read_text()
            # Find today's section
            day_pattern = re_mod.compile(
                rf'###\s*{day_name}.*?(?=###|\Z)',
                re_mod.DOTALL | re_mod.IGNORECASE
            )
            day_match = day_pattern.search(content)
            if day_match:
                section = day_match.group(0)
                tickers = re_mod.findall(r'\*\*([A-Z]{1,5})\*\*', section)
                # Also grab from calendar at-a-glance
                cal_tickers = re_mod.findall(r'\(([A-Z]{1,5})\)', section)
                return list(set(tickers + cal_tickers))
    return []


def main():
    print(f"=== Portfolio Analysis — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    portfolio = load_holdings()
    holdings = portfolio["holdings"]
    summary = portfolio["portfolio_summary"]
    is_stale = portfolio.get("_stale", False)
    stale_date = portfolio.get("_stale_date", "")

    if is_stale:
        print(f"⚠️  Using stale data from {stale_date} (today's fetch failed)")

    print(f"Portfolio Value: ${float(summary.get('equity', 0)):,.2f}")
    print(f"Positions: {len(holdings)}\n")

    # Get tickers reporting earnings today
    earnings_today = get_tickers_reporting_today()
    print(f"Tickers with earnings today: {', '.join(earnings_today) if earnings_today else 'none'}")

    # Fetch technicals for each holding
    print("Fetching technicals...")
    technicals = {}
    holdings_data = []
    for ticker, data in holdings.items():
        tech = fetch_technicals(ticker)
        if tech:
            technicals[ticker] = tech

        has_earnings = ticker in earnings_today
        holdings_data.append({
            "ticker": ticker,
            "shares": float(data.get("quantity", 0)),
            "avg_cost": float(data.get("average_buy_price", 0)),
            "current_price": float(data.get("price", 0)),
            "pnl_pct": float(data.get("percent_change", 0)),
            "equity": float(data.get("equity", 0)),
            "pct_of_portfolio": float(data.get("percentage", 0)),
            "earnings_today": has_earnings,
        })
        earnings_label = " ⚡EARNINGS TODAY" if has_earnings else ""
        print(f"  {ticker}: done{earnings_label}")

    print("\nAnalyzing with Claude Opus 4.6...")
    analysis = analyze_with_claude(holdings_data, technicals)

    # Save analysis
    date_str = datetime.now().strftime("%Y-%m-%d")
    month_str = datetime.now().strftime("%Y-%m")

    stale_warning = ""
    if is_stale:
        stale_warning = f"\n⚠️ **NOTE: Portfolio fetch failed today. Using data from {stale_date}. Prices shown are from that date — technicals are still current.**\n\n"

    earnings_note = ""
    holdings_with_earnings = [h["ticker"] for h in holdings_data if h.get("earnings_today")]
    if holdings_with_earnings:
        earnings_note = f"\n⚡ **EARNINGS TODAY:** {', '.join(holdings_with_earnings)} — check positioning before close.\n\n"

    analysis_content = f"# Portfolio Analysis — {date_str}\n\nPortfolio Value: ${float(summary.get('equity', 0)):,.2f}\n{stale_warning}{earnings_note}{analysis}"

    analysis_path = DATA_DIR / f"{date_str}_analysis.md"
    with open(analysis_path, "w") as f:
        f.write(analysis_content)

    # Upload to S3
    s3 = boto3.client("s3", region_name=REGION)
    s3_key = f"portfolio/{month_str}/{date_str}_analysis.md"
    s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=analysis_content.encode())
    print(f"Uploaded to s3://{S3_BUCKET}/{s3_key}")

    # Also upload holdings JSON
    holdings_json = json.dumps({"portfolio_summary": summary, "holdings": holdings_data, "technicals": technicals}, indent=2)
    s3.put_object(Bucket=S3_BUCKET, Key=f"portfolio/{month_str}/{date_str}.json", Body=holdings_json.encode())

    # Send email
    subject = f"Portfolio Analysis — {date_str}"
    if is_stale:
        subject = f"Portfolio Analysis — {date_str} (using {stale_date} data)"
    if holdings_with_earnings:
        subject += f" ⚡ {', '.join(holdings_with_earnings)} report today"

    ses = boto3.client("ses", region_name=REGION)
    ses.send_email(
        Source=EMAIL_SENDER,
        Destination={"ToAddresses": [EMAIL_RECIPIENT]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": analysis_content, "Charset": "UTF-8"}},
        },
    )
    print("Email sent")

    print(f"\nAnalysis saved to {analysis_path}")
    print("\n" + analysis)


if __name__ == "__main__":
    main()

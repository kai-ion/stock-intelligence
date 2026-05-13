#!/usr/bin/env python3
"""
Weekly Events Report — generates Monday morning brief covering:
1. Major earnings this week (big caps only)
2. Fed/economic events (CPI, PPI, FOMC, retail sales, etc.)
3. Notable IPOs
4. Claude's opinion on each

Runs every Monday at 8:00 AM ET on EC2.
"""

import boto3
import json
import os
import requests
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path
from botocore.config import Config

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-opus-4-6-v1")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
DATA_DIR = Path(__file__).parent / "data"

MIN_MARKET_CAP_B = 5  # Only include companies with market cap > $5B in the report


def get_week_range(next_week=True):
    """Get target week's Monday-Friday range."""
    today = datetime.now()
    if next_week:
        monday = today + timedelta(days=(7 - today.weekday()))
    else:
        monday = today - timedelta(days=today.weekday())
    friday = monday + timedelta(days=4)
    return monday, friday


def fetch_earnings_this_week():
    """Fetch all notable earnings for the target week from NASDAQ API."""
    monday, friday = get_week_range()
    earnings = []

    for d in range(5):
        date = monday + timedelta(days=d)
        date_str = date.strftime("%Y-%m-%d")
        day_name = date.strftime("%A")
        try:
            resp = requests.get(
                f"https://api.nasdaq.com/api/calendar/earnings?date={date_str}",
                headers=HEADERS, timeout=15
            )
            if resp.status_code != 200:
                continue
            rows = resp.json().get("data", {}).get("rows", [])
            for r in rows:
                symbol = r.get("symbol", "").strip()
                name = r.get("name", "")
                eps = r.get("epsForecast", "")
                time = r.get("time", "")

                # Determine before/after
                if "pre-market" in time:
                    timing = "Before Open"
                elif "after-hours" in time:
                    timing = "After Close"
                else:
                    timing = "TBD"

                # Get market cap to filter
                mcap_b = 0
                try:
                    stock = yf.Ticker(symbol)
                    mcap = stock.info.get("marketCap", 0)
                    mcap_b = round(mcap / 1e9, 1) if mcap else 0
                except Exception:
                    pass

                if mcap_b >= MIN_MARKET_CAP_B:
                    industry = ""
                    try:
                        industry = stock.info.get("industry", "")
                    except Exception:
                        pass
                    earnings.append({
                        "ticker": symbol,
                        "name": name,
                        "date": date_str,
                        "day": day_name,
                        "timing": timing,
                        "eps_estimate": eps,
                        "market_cap_b": mcap_b,
                        "industry": industry,
                    })
        except Exception:
            continue

    earnings.sort(key=lambda x: (x["date"], -x["market_cap_b"]))
    return earnings


def fetch_economic_events():
    """Fetch high-impact economic events. Tries both this week and next week APIs."""
    monday, friday = get_week_range()
    filtered = []

    # Try both this week and next week calendar feeds
    urls = [
        "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
    ]

    all_events = []
    for url in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                all_events.extend(resp.json())
        except Exception:
            continue

    for e in all_events:
        if e.get("country") != "USD" or e.get("impact") not in ("High", "Medium"):
            continue
        event_date = e.get("date", "")[:10]
        try:
            ed = datetime.strptime(event_date, "%Y-%m-%d")
            if monday.date() <= ed.date() <= friday.date():
                filtered.append({
                    "date": e.get("date", "")[:16],
                    "title": e.get("title", ""),
                    "impact": e.get("impact", ""),
                    "forecast": e.get("forecast", ""),
                    "previous": e.get("previous", ""),
                })
        except ValueError:
            continue

    # If no events found for target week, include all upcoming high-impact events
    if not filtered:
        for e in all_events:
            if e.get("country") == "USD" and e.get("impact") in ("High", "Medium"):
                event_date = e.get("date", "")[:10]
                today = datetime.now().strftime("%Y-%m-%d")
                if event_date >= today:
                    filtered.append({
                        "date": e.get("date", "")[:16],
                        "title": e.get("title", ""),
                        "impact": e.get("impact", ""),
                        "forecast": e.get("forecast", ""),
                        "previous": e.get("previous", ""),
                    })

    return filtered


def fetch_ipos():
    """Fetch upcoming and recently priced IPOs."""
    try:
        resp = requests.get(
            "https://api.nasdaq.com/api/ipo/calendar?date=2026-05",
            headers=HEADERS, timeout=10
        )
        if resp.status_code != 200:
            return [], []

        data = resp.json().get("data", {})
        priced = data.get("priced", {}).get("rows", [])
        filed = data.get("filed", {}).get("rows", [])

        # Filter to significant IPOs (>$100M)
        notable_priced = []
        for ipo in priced:
            dollar_val = ipo.get("dollarValueOfSharesOffered", "$0").replace("$", "").replace(",", "")
            try:
                if float(dollar_val) >= 100_000_000:
                    notable_priced.append({
                        "ticker": ipo.get("proposedTickerSymbol", ""),
                        "company": ipo.get("companyName", ""),
                        "exchange": ipo.get("proposedExchange", ""),
                        "price": ipo.get("proposedSharePrice", ""),
                        "date": ipo.get("pricedDate", ""),
                        "value": ipo.get("dollarValueOfSharesOffered", ""),
                    })
            except ValueError:
                continue

        notable_filed = []
        for ipo in filed:
            dollar_val = ipo.get("dollarValueOfSharesOffered", "$0").replace("$", "").replace(",", "")
            try:
                if float(dollar_val) >= 100_000_000:
                    notable_filed.append({
                        "ticker": ipo.get("proposedTickerSymbol", ""),
                        "company": ipo.get("companyName", ""),
                        "date": ipo.get("filedDate", ""),
                        "value": ipo.get("dollarValueOfSharesOffered", ""),
                    })
            except (ValueError, TypeError):
                continue

        return notable_priced, notable_filed
    except Exception:
        return [], []


def generate_report_with_claude(earnings, econ_events, ipos_priced, ipos_filed):
    """Have Claude generate the weekly events report."""
    config = Config(read_timeout=300)
    bedrock = boto3.client("bedrock-runtime", region_name=REGION, config=config)

    monday, friday = get_week_range()

    prompt = f"""You are a financial analyst preparing a WEEKLY EVENTS PREVIEW for a swing trader. Week of {monday.strftime('%B %d')} - {friday.strftime('%B %d, %Y')}.

ALL EARNINGS THIS WEEK (for calendar grid — include ALL in the calendar view):
{json.dumps(earnings, indent=2)}

TOP EARNINGS FOR DETAILED ANALYSIS (top 25 by market cap — write detailed BUY/SHORT/AVOID for these):
{json.dumps(sorted(earnings, key=lambda x: x.get('market_cap_b', 0), reverse=True)[:25], indent=2)}

ECONOMIC EVENTS (US, High/Medium impact):
{json.dumps(econ_events, indent=2)}

RECENTLY PRICED IPOs (>$100M):
{json.dumps(ipos_priced, indent=2)}

RECENTLY FILED IPOs (>$100M):
{json.dumps(ipos_filed, indent=2)}

Generate a weekly events report in this exact format:

# Weekly Events Preview — {monday.strftime('%B %d')} - {friday.strftime('%B %d')}

## Calendar At-a-Glance

Create a compact calendar grid showing the week. For each day, list the top 5-8 companies reporting (biggest market caps) with full name and ticker, economic events with time, and any IPOs. Format:

### Monday
Before Open: Company Name (TICKER), Company Name (TICKER), ...
After Close: Company Name (TICKER), Company Name (TICKER), ...
Events: [none or event name + time ET]

### Tuesday
(same format)

(continue for all 5 days)

Then provide the detailed analysis below:

## Earnings to Watch

Group by day (Monday, Tuesday, etc.). For each company reporting, use this format:

**TICKER** — {"{"}Company Name{"}"} | Reports: {"{"}Day, Date{"}"} (Before Open / After Close)
Consensus: EPS ${"{"}est{"}"}, Revenue ${"{"}est{"}"}B
Action: BUY / SHORT / AVOID — one sentence positioning recommendation.
Claude's take: 2-3 sentences. What does the market expect? What would be a surprise? How should a swing trader position? Reference recent sector trends and whether the stock has run up (priced for perfection) or is oversold (easy beat setup).

Note: "Before Open" means earnings release before market opens that day. "After Close" means after 4PM ET.

## Economic Calendar

For each event, use:

**{"{"}Event Name{"}"}** — {"{"}Day{"}"}  {"{"}Time ET{"}"}
Forecast: {"{"}value{"}"} | Previous: {"{"}value{"}"}
Market impact: 1-2 sentences. What does this number mean for equities? What's the trade if it beats/misses?

## IPO Watch

For notable IPOs (priced this week or upcoming):

**TICKER** — {"{"}Company{"}"} | ${"{"}offering size{"}"}
Claude's take: 2-3 sentences. Is this a buy on day 1? What's the thesis? What comparable companies tell us about valuation?

## Week Ahead Summary

3-5 bullet points: What's the biggest risk this week? What's the biggest opportunity? Key levels to watch on SPY/QQQ. Overall positioning recommendation (risk-on, defensive, or balanced).

Rules:
- Be opinionated — "I'd avoid buying before this print" or "This is a clear buy-the-dip setup if CPI comes in soft"
- Reference how each event connects to specific sectors or stocks
- For earnings, mention if the stock has run up into the print (priced for perfection) or is oversold (low expectations = easy beat)
- For IPOs, be honest about whether retail should participate on day 1 or wait for the lock-up expiry fade"""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 8000,
        "messages": [{"role": "user", "content": prompt}]
    })

    response = bedrock.invoke_model(modelId=MODEL_ID, body=body)
    result = json.loads(response["body"].read())
    return result["content"][0]["text"]


def main():
    import sys
    # Pass --this-week to generate for current week instead of next
    next_week = "--this-week" not in sys.argv

    # Override get_week_range globally for this run
    global get_week_range
    _original = get_week_range
    get_week_range = lambda **kwargs: _original(next_week=next_week)

    monday, friday = _original(next_week=next_week)
    print(f"=== Weekly Events Report — {monday.strftime('%Y-%m-%d')} to {friday.strftime('%Y-%m-%d')} ===\n")

    print("Fetching earnings calendar...")
    earnings = fetch_earnings_this_week()
    print(f"  {len(earnings)} major earnings this week")

    print("Fetching economic events...")
    econ_events = fetch_economic_events()
    print(f"  {len(econ_events)} high/medium impact events")

    print("Fetching IPO calendar...")
    ipos_priced, ipos_filed = fetch_ipos()
    print(f"  {len(ipos_priced)} recently priced, {len(ipos_filed)} filed")

    print("\nGenerating report with Claude...")
    report = generate_report_with_claude(earnings, econ_events, ipos_priced, ipos_filed)

    # Save locally
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    date_str = monday.strftime("%Y-%m-%d")
    report_path = DATA_DIR / f"week_{date_str}.md"
    with open(report_path, "w") as f:
        f.write(report)
    print(f"Saved to {report_path}")

    # Upload to S3
    if S3_BUCKET:
        s3 = boto3.client("s3", region_name=REGION)
        month_str = monday.strftime("%Y-%m")
        s3_key = f"events/{month_str}/week_{date_str}.md"
        s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=report.encode())
        print(f"Uploaded to s3://{S3_BUCKET}/{s3_key}")

    # Send email as HTML
    if EMAIL_SENDER and EMAIL_RECIPIENT:
        import re as re_mod
        html = report
        html = re_mod.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re_mod.sub(r'^# (.+)$', r'<h1 style="color:#1a1a1a;border-bottom:2px solid #eee;padding-bottom:8px;">\1</h1>', html, flags=re_mod.MULTILINE)
        html = re_mod.sub(r'^## (.+)$', r'<h2 style="color:#1a1a1a;margin-top:24px;border-bottom:1px solid #eee;padding-bottom:4px;">\1</h2>', html, flags=re_mod.MULTILINE)
        html = re_mod.sub(r'^### (.+)$', r'<h3 style="color:#333;margin-top:16px;">\1</h3>', html, flags=re_mod.MULTILINE)
        html = re_mod.sub(r'^- (.+)$', r'<div style="padding:4px 0 4px 12px;border-left:3px solid #e0e0e0;margin:4px 0;">\1</div>', html, flags=re_mod.MULTILINE)
        html = html.replace("\n\n", "</p><p>").replace("\n", "<br>")
        html = f"""<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="font-family:-apple-system,Arial,sans-serif;margin:0;padding:16px;background:#fff;color:#1a1a1a;font-size:14px;line-height:1.6;">
<p>{html}</p></body></html>"""

        ses = boto3.client("ses", region_name=REGION)
        ses.send_email(
            Source=EMAIL_SENDER,
            Destination={"ToAddresses": [EMAIL_RECIPIENT]},
            Message={
                "Subject": {"Data": f"Weekly Events — {monday.strftime('%b %d')} - {friday.strftime('%b %d')}", "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
            },
        )
        print("Email sent (HTML)")

    print("\n" + report)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
EarningsWhispers "most anticipated" earnings for a given week.

EarningsWhispers ranks each reporting company by a `total` anticipation score
(how many users are following/watching that earnings event) — this is the same
signal behind their famous weekly "most anticipated earnings" calendar. We use
it to filter the weekly report down from ~400 large-caps to the ~25 names retail
swing traders actually care about.

Endpoint: https://www.earningswhispers.com/api/caldata/<YYYYMMDD>  (JSON, no auth)

Follows the wsb_sentiment.py pattern: works from a residential IP; if EC2 is
blocked, weekly_report falls back to the S3 cache written by the local sync.
"""

import json
import requests
from datetime import timedelta

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.earningswhispers.com/calendar",
}

# EarningsWhispers releaseTime codes
RELEASE_TIME = {1: "Before Open", 2: "During Market", 3: "After Close"}


def _fetch_day(date_obj):
    """Fetch one day's earnings rows from EarningsWhispers. Returns [] on failure."""
    ymd = date_obj.strftime("%Y%m%d")
    url = f"https://www.earningswhispers.com/api/caldata/{ymd}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200 and resp.text.strip().startswith("["):
            return resp.json()
    except Exception:
        pass
    return []


def get_anticipated_earnings(monday, top_n=25):
    """
    Return the top N most-anticipated earnings for the Mon-Fri week starting `monday`,
    ranked by EarningsWhispers' anticipation score.

    Each dict matches the schema weekly_report expects:
      ticker, name, date (YYYY-MM-DD), day, timing, eps_estimate,
      market_cap_b (0 — EW doesn't provide it; retained for compatibility),
      industry ("" — not provided), plus anticipation_score and rev_estimate_b.
    """
    all_rows = []
    for d in range(5):
        date_obj = monday + timedelta(days=d)
        date_str = date_obj.strftime("%Y-%m-%d")
        day_name = date_obj.strftime("%A")
        for x in _fetch_day(date_obj):
            ticker = (x.get("ticker") or "").strip()
            if not ticker:
                continue
            eps = x.get("q1EstEPS")
            rev = x.get("q1RevEst")
            all_rows.append({
                "ticker": ticker,
                "name": x.get("company", ticker),
                "date": date_str,
                "day": day_name,
                "timing": RELEASE_TIME.get(x.get("releaseTime"), "TBD"),
                "eps_estimate": f"{eps:.2f}" if isinstance(eps, (int, float)) else "",
                "rev_estimate_b": round(rev / 1e9, 2) if isinstance(rev, (int, float)) and rev else None,
                "anticipation_score": x.get("total", 0) or 0,
                "market_cap_b": 0,   # EW doesn't provide market cap
                "industry": "",
            })

    # Rank by anticipation score, keep top N, then present in day order for the report.
    all_rows.sort(key=lambda r: r["anticipation_score"], reverse=True)
    top = all_rows[:top_n]
    top.sort(key=lambda r: (r["date"], -r["anticipation_score"]))
    return top


if __name__ == "__main__":
    import sys
    from datetime import datetime
    # Default: this week's Monday
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    if len(sys.argv) > 1:
        monday = datetime.strptime(sys.argv[1], "%Y-%m-%d")
    top = get_anticipated_earnings(monday, top_n=25)
    print(f"Top {len(top)} anticipated earnings for week of {monday.strftime('%Y-%m-%d')}:\n")
    for e in top:
        print(f"  {e['ticker']:6} {e['anticipation_score']:4}  {e['day']:9} {e['timing']:13} "
              f"EPS est {e['eps_estimate']:>6}  {e['name'][:28]}")

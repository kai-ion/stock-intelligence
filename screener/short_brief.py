#!/usr/bin/env python3
"""
Short Brief — Claude analyzes top short candidates and sends bearish report.
Runs after short_screener.py generates the CSV.
"""

import boto3
import json
import os
import re
from datetime import datetime
from pathlib import Path
from botocore.config import Config

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-opus-4-6-v1")
OUTPUT_DIR = Path(__file__).parent.parent / "screener_output"


def get_claude_short_analysis(shorts_data):
    """Send top shorts to Claude; return a list of per-ticker recommendation dicts."""
    config = Config(read_timeout=120)
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)

    prompt = f"""You are a bearish stock analyst. Below are today's top short candidates — stocks in confirmed downtrends (below 50-day EMA, negative weekly momentum).

For EACH stock in the list, decide whether it is a clean SHORT or whether it should be AVOIDED (value trap / squeeze risk / bottoming). Then give the trade levels.

STOCKS (sorted by bearish score):
{shorts_data}

Respond with ONLY a JSON array (no markdown, no prose), one object per ticker you have a view on:
[
  {{
    "ticker": "COIN",
    "rec": "SHORT",            // "SHORT" or "AVOID"
    "entry": "152-156",        // entry zone for shorting, or "" if AVOID
    "cover": "125.00",         // downside cover target, or "" if AVOID
    "stop": "168.00",          // stop loss above resistance, or "" if AVOID
    "thesis": "One sentence on why this is a short, or why to avoid it.",
    "top_pick": true           // true ONLY for your top 3 highest-conviction shorts
  }}
]

Cover the strongest 12-15 names as SHORT candidates with trade levels. Use AVOID for 2-3 that look cheap but could bounce (bullish MACD, snapback risk, oversold RSI divergence). Keep each thesis to one sentence.

Then pick your TOP 3 highest-conviction shorts — the ones you would put on TODAY if you could only pick 3. For these, set "top_pick": true in the JSON.

Output valid JSON only."""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}]
    })

    response = bedrock.invoke_model(modelId=MODEL_ID, body=body)
    result = json.loads(response["body"].read())
    text = result["content"][0]["text"]

    # Extract the JSON array (Claude may wrap it in a code fence)
    match = re.search(r"\[.*\]", text, re.DOTALL)
    raw = match.group(0) if match else text
    try:
        recs = json.loads(raw)
    except json.JSONDecodeError:
        print("WARNING: could not parse Claude JSON; got:\n" + text[:500])
        return []
    return recs


def recs_to_markdown(recs, date_str):
    """Render the recommendation list as the markdown brief / email body."""
    top_picks = [r for r in recs if r.get("top_pick") and str(r.get("rec", "")).upper() == "SHORT"]
    shorts = [r for r in recs if str(r.get("rec", "")).upper() == "SHORT"]
    avoids = [r for r in recs if str(r.get("rec", "")).upper() == "AVOID"]

    lines = []

    # Claude's top picks first
    if top_picks:
        lines.append(f"## Claude's Top Shorts — {date_str}")
        lines.append("")
        for r in top_picks:
            lines.append(f"**{r.get('ticker', '?')}** — {r.get('thesis', '')}")
            lines.append(f"- Entry: {r.get('entry', '')} | Cover: {r.get('cover', '')} | Stop: {r.get('stop', '')}")
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## All Short Candidates")
    lines.append("")
    for r in shorts:
        lines.append(f"### {r.get('ticker', '?')}")
        lines.append(f"**Thesis:** {r.get('thesis', '')}")
        lines.append(f"- Short entry: {r.get('entry', '')}")
        lines.append(f"- Cover at: {r.get('cover', '')}")
        lines.append(f"- Stop: {r.get('stop', '')}")
        lines.append("")

    if avoids:
        lines.append("---")
        lines.append("")
        lines.append("## Avoid Shorting")
        lines.append("")
        for r in avoids:
            lines.append(f"### {r.get('ticker', '?')}")
            lines.append(r.get("thesis", ""))
            lines.append("")

    return "\n".join(lines)


def main():
    print(f"=== Short Brief — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    date_str = datetime.now().strftime("%Y-%m-%d")
    month_str = datetime.now().strftime("%Y-%m")

    # Read today's shorts CSV
    csv_path = OUTPUT_DIR / month_str / f"{date_str}_shorts.csv"
    if not csv_path.exists():
        print("No shorts CSV found. Run short_screener.py first.")
        return

    import pandas as pd
    df = pd.read_csv(csv_path)
    top_candidates = df.head(30).to_string(index=False)

    print(f"Analyzing top {min(30, len(df))} of {len(df)} short candidates...")
    recs = get_claude_short_analysis(top_candidates)
    analysis = recs_to_markdown(recs, date_str)

    # Merge Claude's recommendation back into the candidates CSV
    if recs:
        rec_df = pd.DataFrame(recs).rename(columns={
            "ticker": "Ticker",
            "rec": "Claude Rec",
            "entry": "Entry",
            "cover": "Cover",
            "stop": "Stop",
            "thesis": "Thesis",
        })
        rec_cols = ["Ticker", "Claude Rec", "Entry", "Cover", "Stop", "Thesis"]
        rec_df = rec_df[[c for c in rec_cols if c in rec_df.columns]]
        # Drop any stale rec columns before re-merging (idempotent re-runs)
        df = df[[c for c in df.columns if c not in rec_cols[1:]]]
        df = df.merge(rec_df, on="Ticker", how="left")
        df.to_csv(csv_path, index=False)
        print(f"Merged {len(rec_df)} recommendations into {csv_path}")

    # Save brief
    brief_path = OUTPUT_DIR / month_str / f"{date_str}_short_brief.md"
    with open(brief_path, "w") as f:
        f.write(analysis)
    print(f"Saved to {brief_path}")

    # Send email
    s3 = boto3.client("s3", region_name=REGION)
    bucket = os.environ.get("S3_BUCKET", "")
    if bucket:
        s3.put_object(
            Bucket=bucket,
            Key=f"results/{month_str}/{date_str}_short_brief.md",
            Body=analysis.encode()
        )

    ses = boto3.client("ses", region_name=REGION)
    sender = os.environ.get("EMAIL_SENDER", "")
    recipient = os.environ.get("EMAIL_RECIPIENT", "")
    if sender and recipient:
        # Convert markdown to simple HTML
        html = analysis
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'^### (.+)$', r'<h3 style="color:#dc2626;margin:16px 0 4px;">\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2 style="color:#1a1a1a;margin:20px 0 8px;border-bottom:1px solid #eee;padding-bottom:4px;">\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^- (.+)$', r'<div style="padding:3px 0 3px 12px;border-left:3px solid #dc2626;margin:4px 0;">\1</div>', html, flags=re.MULTILINE)
        html = html.replace("\n", "<br>")

        full_html = f"""<html><body style="font-family:-apple-system,Arial,sans-serif;padding:12px;">
<h2 style="color:#dc2626;">Short Screener — {date_str}</h2>
<p style="color:#666;font-size:12px;">{len(df)} stocks below 50d EMA with negative momentum</p>
<div style="font-size:14px;line-height:1.7;">{html}</div>
</body></html>"""

        ses.send_email(
            Source=sender,
            Destination={"ToAddresses": [recipient]},
            Message={
                "Subject": {"Data": f"Short Candidates — {date_str}", "Charset": "UTF-8"},
                "Body": {"Html": {"Data": full_html, "Charset": "UTF-8"}},
            },
        )
        print("Email sent")


if __name__ == "__main__":
    main()

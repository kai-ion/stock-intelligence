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
    """Send top shorts to Claude for analysis."""
    config = Config(read_timeout=120)
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)

    prompt = f"""You are a bearish stock analyst. Below are today's top short candidates — stocks in confirmed downtrends (below 50-day EMA, negative weekly momentum).

For the top 10-15 stocks, write a brief with:
1. Why each is a strong short (catalyst, broken support, sector weakness, bad earnings)
2. Entry zone for shorting (where to initiate)
3. Cover target (where to take profit)
4. Stop loss (where to cut if it bounces)

STOCKS (sorted by bearish score):
{shorts_data}

Format your response as:

## Short Candidates — [date]

### [Ticker] (Day% | Week% | Below EMA%)
**Thesis:** [1-2 sentences on why this is a short]
- Short entry: $X.XX (current level or breakdown below support)
- Cover at: $X.XX (downside target)
- Stop: $X.XX (above recent high or EMA)

Only include stocks where you see a clear SHORT thesis. Skip any that look like they could bounce.
End with a section called "## Avoid Shorting" listing 2-3 from the list that look like value traps (cheap but could bounce).
"""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}]
    })

    response = bedrock.invoke_model(modelId=MODEL_ID, body=body)
    result = json.loads(response["body"].read())
    return result["content"][0]["text"]


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
    top_30 = df.head(30).to_string(index=False)

    print(f"Analyzing {len(df)} short candidates...")
    analysis = get_claude_short_analysis(top_30)

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
        html = re.sub(r'^## (.+)$', r'<h2 style="color:#1a1a1a;margin:20px 0 8px;border-bottom:1px solid #eee;padding-bottom:4px;">\2</h2>', html, flags=re.MULTILINE)
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

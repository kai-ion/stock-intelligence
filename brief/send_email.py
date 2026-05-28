#!/usr/bin/env python3
"""Read screener output, email via SES (HTML), and upload to S3."""

import boto3
import csv
import os
import re
from datetime import datetime

RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "")
SENDER = os.environ.get("EMAIL_SENDER", "")
REGION = os.environ.get("AWS_REGION", "us-east-1")
BUCKET = os.environ.get("S3_BUCKET", "")
OUTPUT_FILE = "/home/ec2-user/output.log"
NEWS_FILE = "/home/ec2-user/news.log"


def parse_results(content):
    """Parse screener output using the CSV file if available, otherwise from text."""
    # Try parsing from the CSV that the screener also generates
    # The CSV is clean with proper column headers and no spacing issues
    csv_path = "/home/ec2-user/output.csv"
    if os.path.exists(csv_path):
        import csv as csv_mod
        with open(csv_path) as f:
            reader = csv_mod.DictReader(f)
            headers = reader.fieldnames
            rows = []
            for r in reader:
                rows.append([r[h] for h in headers])
            return headers, rows

    # Fallback: parse from text output
    lines = content.strip().split("\n")
    header_idx = None
    for i, line in enumerate(lines):
        if "Ticker" in line and "Price" in line and "Momentum" in line:
            header_idx = i
            break
    if header_idx is None:
        return [], []

    # Determine column order from actual header
    header_line = lines[header_idx]
    # Use fixed-position parsing based on column header character positions
    import re as re_local
    col_positions = [(m.start(), m.group()) for m in re_local.finditer(r'\S+(?:\s\S+)*?(?=\s{2,}|\s*$)', header_line)]

    # Simpler approach: we know the data format, parse with known field count from ends
    # Numeric fields from the right: Rating Momentum VolRatio ROC20% MACDHist MACD RSI AboveEMA%
    # Then text fields in the middle (Sector, possibly Industry)
    # Left side: idx Ticker Price Day% Week% MCap($B)
    headers = ["Ticker", "Price", "Day%", "Week%", "MCap($B)", "Sector",
               "Above EMA%", "RSI", "MACD", "MACD Hist", "ROC20%", "Vol Ratio", "Momentum", "Rating"]

    rows = []
    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 10:
            continue
        try:
            # From the right, count back 8 numeric/keyword fields
            # Rating, Momentum, VolRatio, ROC20, MACDHist, MACD(Bull/Bear), RSI, AboveEMA
            rating = parts[-1]
            momentum = parts[-2]
            vol_ratio = parts[-3]
            roc20 = parts[-4]
            macd_hist = parts[-5]
            macd = parts[-6]
            rsi = parts[-7]
            above_ema = parts[-8]

            # From the left (skip index): Ticker Price Day% Week% MCap
            ticker = parts[1]
            price = parts[2]
            day = parts[3]
            week = parts[4]
            mcap = parts[5]

            # Middle is sector (may have spaces)
            sector = " ".join(parts[6:-8])

            row = [ticker, price, day, week, mcap, sector,
                   above_ema, rsi, macd, macd_hist, roc20, vol_ratio, momentum, rating]
            rows.append(row)
        except IndexError:
            continue
    return headers, rows


def build_html(date_str, headers, rows, total_count):
    """Build mobile-friendly HTML email — brief first, screener table last."""
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body {{ font-family: -apple-system, Arial, sans-serif; margin: 0; padding: 12px; background: #ffffff; color: #1a1a1a; }}
h2 {{ color: #1a1a1a; margin-bottom: 4px; font-size: 18px; }}
p {{ color: #666; font-size: 12px; margin-top: 0; }}
table {{ border-collapse: collapse; width: 100%; font-size: 11px; }}
th {{ background: #f0f4f8; color: #1a1a1a; padding: 8px 6px; text-align: left; border-bottom: 2px solid #ddd; font-weight: 600; }}
td {{ padding: 6px; border-bottom: 1px solid #eee; }}
tr:nth-child(even) {{ background: #f9fafb; }}
.pos {{ color: #16a34a; font-weight: 500; }}
.neg {{ color: #dc2626; font-weight: 500; }}
.ticker {{ font-weight: bold; color: #111; }}
</style>
</head>
<body>
<h2>Stock Screener — {date_str}</h2>
<p>{total_count} stocks passed | Above 50d EMA | +Week | MCap &gt;$1B | Sorted by Momentum</p>
"""

    # News brief first (top movers, Claude's picks, WSB, earnings)
    if os.path.exists(NEWS_FILE):
        with open(NEWS_FILE) as f:
            news_content = f.read().strip()
        if news_content:
            import re as re_mod
            news_html = news_content
            news_html = re_mod.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', news_html)
            news_html = re_mod.sub(r'^### (.+)$', r'<h4 style="color:#1a1a1a;margin:12px 0 4px;">\1</h4>', news_html, flags=re_mod.MULTILINE)
            news_html = re_mod.sub(r'^## (.+)$', r'<h3 style="color:#1a1a1a;margin:16px 0 6px;border-bottom:1px solid #eee;padding-bottom:4px;">\1</h3>', news_html, flags=re_mod.MULTILINE)
            news_html = re_mod.sub(r'^# (.+)$', r'<h2 style="color:#1a1a1a;margin:16px 0 6px;">\1</h2>', news_html, flags=re_mod.MULTILINE)
            news_html = news_html.replace("---", '<hr style="border-color:#eee;margin:12px 0;">')
            news_html = re_mod.sub(r'\*(.+?)\*', r'<em style="color:#666;">\1</em>', news_html)
            news_html = re_mod.sub(r'^- (.+)$', r'<div style="padding:4px 0 4px 12px;border-left:3px solid #e0e0e0;margin:6px 0;">\1</div>', news_html, flags=re_mod.MULTILINE)
            news_html = news_html.replace("\n", "<br>")

            html += f"""<div style="font-size: 13px; line-height: 1.7; color: #333;">
{news_html}
</div>
"""

    # Screener CSV table at the bottom
    key_cols = ["Ticker", "Price", "Day%", "Week%", "MCap($B)", "Sector", "Industry", "Momentum", "Rating", "Vol Ratio"]
    col_indices = []
    display_headers = []
    for col in key_cols:
        if col in headers:
            col_indices.append(headers.index(col))
            display_headers.append(col)

    html += f"""<hr style="border-color: #eee; margin: 20px 0;">
<h3 style="color:#1a1a1a;margin:12px 0 6px;">Full Screener Output</h3>
<table>
<tr>{"".join(f"<th>{h}</th>" for h in display_headers)}</tr>
"""

    for row in rows:
        html += "<tr>"
        for idx in col_indices:
            if idx >= len(row):
                html += "<td>-</td>"
                continue
            val = row[idx]
            col_name = headers[idx]
            if col_name == "Ticker":
                html += f'<td class="ticker">{val}</td>'
            elif col_name in ("Day%", "Week%", "ROC20%"):
                try:
                    cls = "pos" if float(val) >= 0 else "neg"
                    html += f'<td class="{cls}">{val}</td>'
                except ValueError:
                    html += f"<td>{val}</td>"
            else:
                html += f"<td>{val}</td>"
        html += "</tr>\n"

    html += "</table>\n</body>\n</html>"
    return html


def main():
    if not os.path.exists(OUTPUT_FILE):
        print("ERROR: No output file found")
        return

    with open(OUTPUT_FILE) as f:
        content = f.read()

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    month_str = now.strftime("%Y-%m")

    # Upload full results to S3 (txt + csv)
    s3 = boto3.client("s3", region_name=REGION)
    s3_key = f"results/{month_str}/{date_str}.txt"
    s3.put_object(Bucket=BUCKET, Key=s3_key, Body=content.encode())
    print(f"Uploaded to s3://{BUCKET}/{s3_key}")

    # Upload CSV version
    headers_parsed, rows_parsed = parse_results(content)
    if headers_parsed and rows_parsed:
        csv_lines = [",".join(headers_parsed)]
        for row in rows_parsed:
            csv_lines.append(",".join(f'"{v}"' if "," in v else v for v in row))
        csv_content = "\n".join(csv_lines)
        csv_key = f"results/{month_str}/{date_str}.csv"
        s3.put_object(Bucket=BUCKET, Key=csv_key, Body=csv_content.encode())
        print(f"Uploaded to s3://{BUCKET}/{csv_key}")

    # Upload news brief
    if os.path.exists(NEWS_FILE):
        with open(NEWS_FILE) as f:
            news_content = f.read()
        news_key = f"results/{month_str}/{date_str}_brief.md"
        s3.put_object(Bucket=BUCKET, Key=news_key, Body=news_content.encode())
        print(f"Uploaded to s3://{BUCKET}/{news_key}")

    # Parse and build HTML email
    headers, rows = parse_results(content)
    if not rows:
        print("ERROR: Could not parse results")
        return

    # Count from output
    count_match = re.search(r"(\d+) stocks passed", content)
    total_count = count_match.group(1) if count_match else len(rows)

    html = build_html(date_str, headers, rows, total_count)

    ses = boto3.client("ses", region_name=REGION)
    ses.send_email(
        Source=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Message={
            "Subject": {"Data": f"Stock Screener — {date_str}", "Charset": "UTF-8"},
            "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
        },
    )
    print("Email sent successfully")


if __name__ == "__main__":
    main()

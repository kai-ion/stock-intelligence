#!/usr/bin/env python3
"""Read screener output and post to Slack."""

import json
import os
import requests

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
OUTPUT_FILE = "/home/ec2-user/output.log"

def main():
    if not SLACK_WEBHOOK_URL:
        print("ERROR: SLACK_WEBHOOK_URL not set")
        return

    if not os.path.exists(OUTPUT_FILE):
        print("ERROR: No output file found")
        return

    with open(OUTPUT_FILE) as f:
        content = f.read()

    # Slack has a 3000 char limit per block; split if needed
    header = content[:content.find("==" * 40)] if "==" * 40 in content else ""
    table_start = content.find("  Ticker")
    if table_start == -1:
        message = content[:3000]
    else:
        message = content[table_start:]

    # Take top 30 lines of the table
    lines = message.strip().split("\n")
    top_30 = "\n".join(lines[:31])

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Morning Stock Screener"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Above 50d EMA | Positive week | MCap >$1B | Sorted by momentum"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```{top_30}```"}
            }
        ]
    }

    resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
    print(f"Slack response: {resp.status_code} {resp.text}")

if __name__ == "__main__":
    main()

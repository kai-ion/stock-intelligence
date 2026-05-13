#!/usr/bin/env python3
"""
Trump Statement Monitor — polls Truth Social and White House for market-moving statements.
Runs every 5 minutes during market hours. Alerts via email for high-severity items,
batches low-severity into the morning digest.
"""

import requests
import re
import json
import os
import boto3
import hashlib
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from botocore.config import Config

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-opus-4-6-v1")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
DATA_DIR = Path(__file__).parent / "data"
SEEN_FILE = DATA_DIR / "seen_posts.json"
DIGEST_FILE = DATA_DIR / "daily_digest.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# Keywords that suggest market relevance
MARKET_KEYWORDS = [
    # Companies/sectors
    "apple", "google", "amazon", "microsoft", "nvidia", "tesla", "meta",
    "dell", "intel", "boeing", "lockheed", "raytheon", "pfizer", "moderna",
    "stock", "market", "dow", "nasdaq", "s&p",
    # Trade/policy
    "tariff", "trade", "deal", "china", "eu", "europe", "japan", "mexico",
    "canada", "import", "export", "sanction", "ban", "restrict",
    # Economic
    "tax", "rate", "fed", "interest", "inflation", "jobs", "economy",
    "billion", "trillion", "invest", "manufacturing",
    # Actions
    "executive order", "sign", "announce", "buy", "american",
    "oil", "gas", "energy", "drill", "pipeline",
]


def load_seen():
    """Load previously seen post IDs."""
    if SEEN_FILE.exists():
        with open(SEEN_FILE) as f:
            return json.load(f)
    return []


def save_seen(seen):
    """Save seen post IDs."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Keep last 500 to prevent unbounded growth
    with open(SEEN_FILE, "w") as f:
        json.dump(seen[-500:], f)


def load_digest():
    """Load today's digest items."""
    if DIGEST_FILE.exists():
        with open(DIGEST_FILE) as f:
            data = json.load(f)
            if data.get("date") == datetime.now().strftime("%Y-%m-%d"):
                return data.get("items", [])
    return []


def save_digest(items):
    """Save today's digest items."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DIGEST_FILE, "w") as f:
        json.dump({"date": datetime.now().strftime("%Y-%m-%d"), "items": items}, f)


def fetch_trump_telegram():
    """Fetch Trump quotes from TrumpWarRoom Telegram channel."""
    posts = []
    try:
        resp = requests.get("https://t.me/s/TrumpWarRoom", headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            messages = soup.find_all("div", class_="tgme_widget_message_wrap")
            for msg in messages:
                text_div = msg.find("div", class_="tgme_widget_message_text")
                if not text_div:
                    continue
                text = text_div.get_text(strip=True)
                if not text or len(text) < 10:
                    continue

                # Get message ID from data attribute
                msg_div = msg.find("div", class_="tgme_widget_message")
                msg_id = msg_div.get("data-post", "") if msg_div else ""
                post_id = hashlib.md5(text.encode()).hexdigest()[:12]

                # Get timestamp
                time_el = msg.find("time")
                timestamp = time_el.get("datetime", "") if time_el else ""

                posts.append({
                    "source": "trump_telegram",
                    "id": post_id,
                    "text": text[:500],
                    "timestamp": timestamp,
                })
    except Exception as e:
        print(f"  Telegram error: {e}")
    return posts


def fetch_truth_social_api():
    """Attempt Truth Social API — content may be empty but try anyway."""
    posts = []
    try:
        resp = requests.get(
            "https://truthsocial.com/api/v1/accounts/107780257626128497/statuses?limit=10",
            headers=HEADERS, timeout=10
        )
        if resp.status_code == 200:
            for p in resp.json():
                content = re.sub("<[^>]+>", "", p.get("content", ""))
                if content.strip():
                    posts.append({
                        "source": "truth_social",
                        "id": p["id"],
                        "text": content.strip(),
                        "timestamp": p.get("created_at", ""),
                    })
    except Exception as e:
        print(f"  Truth Social API error: {e}")
    return posts


def fetch_white_house():
    """Scrape White House statements and presidential actions."""
    posts = []
    urls = [
        "https://www.whitehouse.gov/briefing-room/statements-releases/",
        "https://www.whitehouse.gov/presidential-actions/",
    ]
    for url in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # Find article/post links
                for article in soup.find_all(["article", "li", "div"], class_=re.compile("post|entry|item|news")):
                    link = article.find("a")
                    if link:
                        title = link.get_text(strip=True)
                        href = link.get("href", "")
                        if title and len(title) > 10:
                            post_id = hashlib.md5(title.encode()).hexdigest()[:12]
                            posts.append({
                                "source": "white_house",
                                "id": post_id,
                                "text": title,
                                "timestamp": datetime.now().isoformat(),
                                "url": href,
                            })
        except Exception as e:
            print(f"  White House error ({url}): {e}")
    return posts


def keyword_filter(posts):
    """Pre-filter posts by market-relevant keywords."""
    filtered = []
    for post in posts:
        text_lower = post["text"].lower()
        matched_keywords = [kw for kw in MARKET_KEYWORDS if kw in text_lower]
        if matched_keywords:
            post["matched_keywords"] = matched_keywords
            filtered.append(post)
    return filtered


def classify_with_claude(posts):
    """Use Claude to classify severity: IMMEDIATE, DIGEST, or IGNORE."""
    if not posts:
        return []

    config = Config(read_timeout=120)
    bedrock = boto3.client("bedrock-runtime", region_name=REGION, config=config)

    prompt = f"""You are a financial analyst monitoring Trump's statements for market impact. Today is {datetime.now().strftime('%Y-%m-%d %H:%M')}.

POSTS TO CLASSIFY:
{json.dumps(posts, indent=2)}

For EACH post, classify its market impact severity:

**IMMEDIATE** — Direct company mention, tariff announcement, trade deal, executive order affecting markets, or policy that would move specific stocks or sectors TODAY. These need instant alerts.

**DIGEST** — General economic commentary, broad policy direction, sector-level statements that provide context but won't cause immediate price action. Batch these for the morning brief.

**IGNORE** — Political commentary, rally promotion, personal attacks, non-market content that passed the keyword filter but isn't actually market-relevant.

Respond in this exact JSON format:
[
  {{"id": "post_id", "severity": "IMMEDIATE|DIGEST|IGNORE", "summary": "one sentence on market impact", "tickers_affected": ["TICKER1", "TICKER2"], "expected_direction": "bullish|bearish|neutral"}}
]

Rules:
- Company name-drops are ALWAYS IMMEDIATE (remember the Dell pump)
- Tariff numbers/percentages are IMMEDIATE
- "We're looking at..." or "Maybe we'll..." is DIGEST, not IMMEDIATE
- Campaign rhetoric about the economy is IGNORE
- Be conservative — only IMMEDIATE if it would actually move prices today"""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1500,
        "messages": [{"role": "user", "content": prompt}]
    })

    response = bedrock.invoke_model(modelId=MODEL_ID, body=body)
    result = json.loads(response["body"].read())
    text = result["content"][0]["text"]

    # Parse JSON from response
    try:
        json_match = re.search(r"\[.*\]", text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except (json.JSONDecodeError, AttributeError):
        pass
    return []


def send_immediate_alert(post, classification):
    """Send immediate email alert for high-severity posts."""
    ses = boto3.client("ses", region_name=REGION)

    tickers = ", ".join(classification.get("tickers_affected", [])) or "Broad market"
    direction = classification.get("expected_direction", "unknown")
    direction_emoji = "UP" if direction == "bullish" else "DOWN" if direction == "bearish" else "UNCERTAIN"

    body = f"""TRUMP MARKET ALERT — {direction_emoji}

Source: {post['source'].replace('_', ' ').title()}
Time: {post.get('timestamp', 'just now')}

Statement:
"{post['text']}"

Market Impact: {classification.get('summary', 'N/A')}
Tickers Affected: {tickers}
Expected Direction: {direction.upper()}

---
Matched keywords: {', '.join(post.get('matched_keywords', []))}
"""

    ses.send_email(
        Source=EMAIL_SENDER,
        Destination={"ToAddresses": [EMAIL_RECIPIENT]},
        Message={
            "Subject": {"Data": f"TRUMP ALERT: {classification.get('summary', post['text'][:50])}", "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
        },
    )
    print(f"  ALERT SENT: {classification.get('summary', '')}")


def main():
    now = datetime.now()
    print(f"=== Trump Monitor — {now.strftime('%Y-%m-%d %H:%M')} ===")

    # Load state
    seen = load_seen()
    digest = load_digest()

    # Fetch from all sources
    print("Fetching Trump Telegram (TrumpWarRoom)...")
    telegram_posts = fetch_trump_telegram()
    print(f"  Got {len(telegram_posts)} posts")

    print("Fetching Truth Social API...")
    truth_posts = fetch_truth_social_api()
    print(f"  Got {len(truth_posts)} posts")

    print("Fetching White House...")
    wh_posts = fetch_white_house()
    print(f"  Got {len(wh_posts)} posts")

    # Combine and deduplicate
    all_posts = telegram_posts + truth_posts + wh_posts
    new_posts = [p for p in all_posts if p["id"] not in seen]

    # On first run (large batch), only process last 20 to avoid historical alert spam
    if len(new_posts) > 30:
        print(f"\nFirst run detected ({len(new_posts)} posts). Processing only most recent 20.")
        new_posts = new_posts[-20:]

    print(f"\nNew posts: {len(new_posts)}")

    if not new_posts:
        print("No new posts. Done.")
        return

    # Mark as seen
    seen.extend([p["id"] for p in new_posts])
    save_seen(seen)

    # Keyword pre-filter
    relevant = keyword_filter(new_posts)
    print(f"Keyword matches: {len(relevant)}")

    if not relevant:
        print("No market-relevant posts. Done.")
        return

    # Claude classification
    print("Classifying with Claude...")
    classifications = classify_with_claude(relevant)

    for cls in classifications:
        post = next((p for p in relevant if p["id"] == cls["id"]), None)
        if not post:
            continue

        severity = cls.get("severity", "IGNORE")
        print(f"  [{severity}] {cls.get('summary', '')[:80]}")

        if severity == "IMMEDIATE":
            send_immediate_alert(post, cls)
        elif severity == "DIGEST":
            digest.append({
                "timestamp": post.get("timestamp", now.isoformat()),
                "source": post["source"],
                "text": post["text"][:200],
                "summary": cls.get("summary", ""),
                "tickers": cls.get("tickers_affected", []),
                "direction": cls.get("expected_direction", "neutral"),
            })
            save_digest(digest)

    print(f"\nDone. Digest items today: {len(digest)}")


if __name__ == "__main__":
    main()

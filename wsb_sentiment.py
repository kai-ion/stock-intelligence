#!/usr/bin/env python3
"""
Scrape WallStreetBets for top trending tickers and their sentiment.
Returns top 5 tickers with post context for Claude to evaluate.
"""

import requests
import re
import json
from collections import Counter

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# Common words that look like tickers but aren't
EXCLUDE = {
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HER",
    "WAS", "ONE", "OUR", "OUT", "HAS", "HIS", "HOW", "ITS", "MAY", "NEW",
    "NOW", "OLD", "SEE", "WAY", "WHO", "DID", "GET", "LET", "SAY", "SHE",
    "TOO", "USE", "DAD", "MOM", "BIG", "TOP", "PUT", "END", "WHY", "TRY",
    "ASK", "OWN", "OFF", "RUN", "YET", "SET", "LOT", "YOLO", "LMAO", "EDIT",
    "JUST", "LIKE", "THIS", "THAT", "WITH", "HAVE", "FROM", "THEY", "BEEN",
    "WHAT", "WHEN", "MAKE", "KNOW", "WILL", "EACH", "MUCH", "SOME", "THAN",
    "THEM", "VERY", "WEEK", "HOLD", "SELL", "DOWN", "OVER", "SUCH", "TAKE",
    "INTO", "YEAR", "YOUR", "GOOD", "GIVE", "MOST", "ONLY", "TELL", "ALSO",
    "BACK", "EVEN", "WANT", "DOES", "LONG", "HIGH", "BEST", "MOVE", "KEEP",
    "HELP", "NEXT", "LAST", "GAIN", "LOSS", "BULL", "BEAR", "PUMP", "DUMP",
    "MOON", "BAGS", "CALL", "PUTS", "TLDR", "FOMO", "HODL", "YALL", "DONT",
    "CANT", "SAFE", "FREE", "REAL", "FEEL", "LOOK", "WORK", "PLAY", "NEED",
    "HOME", "LIFE", "FIND", "HERE", "LOVE", "BEEN", "MADE", "WENT", "COME",
    "WELL", "MORE", "BEEN", "TURN", "CASH", "SAME", "HOPE", "PART", "HAND",
    "STOP", "LOST", "EVER", "OPEN", "DONE", "SURE", "ELSE", "READ", "PAYS",
    "OTM", "ITM", "ATM", "RSI", "EPS", "CEO", "CFO", "IPO", "ETF", "SEC",
    "GDP", "CPI", "FED", "IMO", "ATH", "USA", "USD", "EUR", "GBP", "LOL",
    "WSB", "DD", "US", "AI", "EV", "UK", "EU", "OP", "PM", "AM", "US",
    "JUST", "STILL", "TODAY", "GOING", "THINK", "ABOUT", "AFTER", "EVERY",
    "MONEY", "STOCK", "SHORT", "SHARE", "PRICE", "VALUE", "TRADE",
}

TICKER_PATTERN = re.compile(r'(?<![a-zA-Z])[A-Z]{2,5}(?![a-zA-Z])')


def scrape_wsb():
    """Get WSB trending data from ApeWisdom API (works from any IP, no auth)."""
    posts = []

    # Primary: ApeWisdom API — aggregates WSB mentions, works everywhere
    try:
        resp = requests.get(
            "https://apewisdom.io/api/v1.0/filter/all-stocks/page/1",
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            for r in results[:30]:
                posts.append({
                    "title": f"{r.get('ticker', '')} — {r.get('mentions', 0)} mentions on WSB",
                    "text": "",
                    "score": r.get("upvotes", 0),
                    "comments": r.get("mentions", 0),
                    "upvote_ratio": 0.7,
                })
            return posts
    except Exception:
        pass

    # Fallback: Reddit JSON API (works locally, blocked on EC2)
    for sort in ["hot", "rising", "new"]:
        try:
            resp = requests.get(
                f"https://www.reddit.com/r/wallstreetbets/{sort}.json?limit=50",
                headers=HEADERS, timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                for p in data["data"]["children"]:
                    d = p["data"]
                    posts.append({
                        "title": d.get("title", ""),
                        "text": d.get("selftext", "")[:500],
                        "score": d.get("score", 0),
                        "comments": d.get("num_comments", 0),
                        "upvote_ratio": d.get("upvote_ratio", 0.5),
                    })
        except Exception:
            continue

    return posts


def extract_tickers(posts):
    """Extract and rank tickers by weighted mentions."""
    ticker_counts = Counter()
    ticker_posts = {}
    ticker_sentiment_signals = {}

    for post in posts:
        text = post["title"] + " " + post["text"]
        matches = set(TICKER_PATTERN.findall(text))
        weight = max(1, post["score"] // 50) + max(1, post["comments"] // 20)

        # Sentiment signals from post title
        title_lower = post["title"].lower()
        is_bullish = any(w in title_lower for w in ["moon", "rocket", "yolo", "diamond", "holding", "bought", "calls", "bull", "squeeze", "🚀", "💎", "gain", "profit", "million"])
        is_bearish = any(w in title_lower for w in ["puts", "short", "crash", "dump", "sell", "loss", "bear", "rip", "bag"])

        for m in matches:
            if m not in EXCLUDE:
                ticker_counts[m] += weight
                if m not in ticker_posts:
                    ticker_posts[m] = []
                    ticker_sentiment_signals[m] = {"bullish": 0, "bearish": 0, "neutral": 0}
                ticker_posts[m].append(post["title"][:120])
                if is_bullish:
                    ticker_sentiment_signals[m]["bullish"] += weight
                elif is_bearish:
                    ticker_sentiment_signals[m]["bearish"] += weight
                else:
                    ticker_sentiment_signals[m]["neutral"] += weight

    return ticker_counts, ticker_posts, ticker_sentiment_signals


def get_wsb_trending(n=5):
    """Get top N trending WSB tickers with sentiment context."""
    # Try ApeWisdom first (direct ticker data, no extraction needed)
    try:
        resp = requests.get(
            "https://apewisdom.io/api/v1.0/filter/all-stocks/page/1",
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            results_raw = data.get("results", [])

            # Filter out index ETFs and get top N actual stocks
            skip = {"SPY", "QQQ", "VOO", "IWM", "DIA", "VTI", "DTE", "OTM", "ITM", "ATM", "ETF"}
            results = []
            for r in results_raw:
                ticker = r.get("ticker", "")
                if ticker in skip or len(ticker) < 2:
                    continue
                if len(results) >= n:
                    break

                mentions = r.get("mentions", 0)
                upvotes = r.get("upvotes", 0)
                mentions_24h_ago = r.get("mentions_24h_ago", mentions)

                # Determine sentiment from momentum (more mentions = bullish bias on WSB)
                if mentions > mentions_24h_ago * 1.5:
                    sentiment_label = "BULLISH"
                    bull_pct = 80
                elif mentions < mentions_24h_ago * 0.7:
                    sentiment_label = "BEARISH"
                    bull_pct = 30
                else:
                    sentiment_label = "MIXED"
                    bull_pct = 55

                results.append({
                    "ticker": ticker,
                    "mentions_score": mentions,
                    "sentiment": sentiment_label,
                    "bullish_pct": bull_pct,
                    "upvotes": upvotes,
                    "sample_posts": [f"{ticker} — {mentions} mentions, {upvotes} upvotes on WSB in last 24h"],
                })

            if results:
                return results
    except Exception:
        pass

    # Fallback: scrape Reddit directly and extract tickers
    posts = scrape_wsb()
    if not posts:
        return []

    ticker_counts, ticker_posts, ticker_sentiment = extract_tickers(posts)

    results = []
    for ticker, count in ticker_counts.most_common(n * 2):
        if len(ticker) == 2 and count < 20:
            continue
        if len(results) >= n:
            break

        sentiment = ticker_sentiment.get(ticker, {})
        bull = sentiment.get("bullish", 0)
        bear = sentiment.get("bearish", 0)
        neutral = sentiment.get("neutral", 0)
        total = bull + bear + neutral

        if total > 0:
            sentiment_label = "BULLISH" if bull > bear * 1.5 else "BEARISH" if bear > bull * 1.5 else "MIXED"
            bull_pct = round(bull / total * 100)
        else:
            sentiment_label = "NEUTRAL"
            bull_pct = 50

        results.append({
            "ticker": ticker,
            "mentions_score": count,
            "sentiment": sentiment_label,
            "bullish_pct": bull_pct,
            "sample_posts": ticker_posts.get(ticker, [])[:3],
        })

    return results


if __name__ == "__main__":
    trending = get_wsb_trending(5)
    print(json.dumps(trending, indent=2))

---
layout: page
title: How It Works
permalink: /about/
---

# How It Works

## Screening

Every weekday, we screen ~2,700 US-traded stocks with market cap above $1B. Stocks must pass:
- Price above 50-day EMA (trend confirmation)
- Positive weekly gain (momentum)
- Sorted by composite momentum score: MACD histogram (35%) + 20-day rate of change (30%) + volume ratio (25%) + EMA spread (10%)

## Technical Analysis

Each stock gets a full technical workup:
- Fibonacci retracements (0.236, 0.382, 0.5, 0.618) from the 6-month swing for support levels
- Fibonacci extensions (1.272, 1.618) for exit targets
- 50-day and 200-day simple moving averages
- 14-day RSI and MACD histogram
- Volume ratio vs 20-day average
- 20-day high/low for immediate support/resistance

## Claude's Analysis

Claude Opus 4.6 receives the screener data, technicals, news headlines, and WSB sentiment. It generates:
- **Thesis** per stock — combining fundamental catalyst with technical setup
- **Exit target** — referenced to specific fib levels, prior resistance, or analyst targets
- **Support/stop** — fib retracements, SMAs, or 20-day lows
- **Top Picks** — 3-5 highest conviction swing trades
- **Avoid list** — overextended or weak-catalyst names
- **WSB Sentiment Check** — agrees or disagrees with retail consensus

## Paper Trading Rules

- Starting capital: $10,000
- Position sizing: 20% per pick (max 5 positions)
- Auto-sell at exit target (fib extension) or stop loss (fib support)
- If no cash for new picks, sells the weakest performer
- Checked twice daily: 10:02 AM (buy + exit check) and 3:55 PM (exit check)
- No manual intervention — fully automated

## Data Sources

- **Price/Technicals**: Yahoo Finance (yfinance)
- **Universe**: NASDAQ Screener API
- **News**: Yahoo Finance per-ticker news
- **Economic Calendar**: FairEconomy (ForexFactory data)
- **Earnings Calendar**: NASDAQ API
- **WSB Sentiment**: Reddit public API (r/wallstreetbets)
- **Trump Monitor**: Telegram (@TrumpWarRoom) + White House statements

## Cost

Runs on a single t2.micro EC2 instance (~$8.50/mo or free tier) plus AWS Bedrock for Claude API calls (~$20-25/mo). Total: ~$30/month.

---

*Not financial advice. This is an experimental AI system. Past performance does not indicate future results.*

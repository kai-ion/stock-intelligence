---
layout: default
title: AI Agent
permalink: /ai-agent/
---



Powered by [TradingAgents](https://github.com/TauricResearch/TradingAgents) (77K+ stars, [arXiv:2412.20138](https://arxiv.org/abs/2412.20138)).

Four AI agents independently analyze each stock, then debate bull vs. bear before a risk manager and portfolio manager make the final call.

## How It Works

```
Market Analyst → Technical signals + sector context
Fundamentals Analyst → Revenue, margins, valuation
Social Sentiment Analyst → Reddit/WSB/social signals  
News Analyst → Headlines, catalysts, macro
        ↓
    Bull vs Bear Debate (2 rounds)
        ↓
    Risk Manager validates constraints
        ↓
    Portfolio Manager: final BUY/SELL/HOLD
```

**Learning:** Every Friday, the system reflects on the week's trades — what worked, what didn't — and stores lessons in memory for future decisions.

## Current Portfolio

{% include ai_agent_portfolio.html %}

## Recent Decisions

{% assign sorted_decisions = site.ai_agent | sort: "date" | reverse %}
{% for post in sorted_decisions limit:7 %}
- [{{ post.title }}]({{ post.url | relative_url }})
{% endfor %}

---

## About TradingAgents

[TradingAgents](https://github.com/TauricResearch/TradingAgents) is an open-source multi-agent financial trading framework by [Tauric Research](https://github.com/TauricResearch) with 77,000+ stars on GitHub. It's backed by academic research published at [arXiv:2412.20138](https://arxiv.org/abs/2412.20138), demonstrating that multi-agent debate systems outperform single-agent analysis in stock trading decisions.

### Key Features

| Feature | Description |
|---------|-------------|
| **Multi-Agent Debate** | Bull and bear analysts argue over each stock across multiple rounds before a decision is made |
| **4 Specialized Analysts** | Market (technicals), Fundamentals (financials), Social (Reddit/sentiment), News (catalysts) |
| **Risk Manager** | Independent agent that challenges proposed trades and validates constraints before execution |
| **Portfolio Manager** | Synthesizes all signals + debate outcomes into final BUY/SELL/HOLD with position sizing |
| **Reflection & Memory** | Learns from past mistakes — every Friday feeds P&L outcomes back into memory for future decisions |
| **Checkpoint/Resume** | Saves state mid-analysis so crashed runs can resume |

### How We Use It

We modified TradingAgents to use **AWS Bedrock** (Claude Sonnet 4.6 for deep thinking, Claude Haiku 4.5 for fast classification) instead of OpenAI, and connected it to the same stock universe as our daily screener.

**Daily process (10:10 AM ET):**
1. Takes the top 5 movers from today's screener
2. Each of the 4 analysts independently researches the stock
3. Bull and Bear agents debate for 2 rounds
4. Risk Manager validates position sizing and constraints
5. Portfolio Manager makes final decision with entry price and stop loss
6. Buys are executed in the paper portfolio

**Friday reflection:**
- Calculates the week's P&L on all closed trades
- Feeds outcomes into TradingAgents' memory system
- Next week's decisions are informed by what worked and what didn't

### Why Compare Two Strategies?

| | Strategy A (Claude) | Strategy B (TradingAgents) |
|---|---|---|
| Decision method | Single analyst with fib levels + news | 4 agents debate bull vs bear |
| Debate | No — one opinion | Yes — arguments challenged |
| Learning | No — fresh each day | Yes — remembers past mistakes |
| Speed | ~3 min per report | ~5 min per stock (more thorough) |
| Cost | ~$0.50/day | ~$2-3/day (more API calls) |

The hypothesis: **a system that debates itself and learns from failures should outperform a single-analyst system over time**, even if both use the same data. This experiment tests that hypothesis with real-time paper trading.

### Source Code

- Framework: [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
- Our integration: [trading_agents/](https://github.com/kai-ion/stock-intelligence/tree/main/trading_agents)
- Bedrock adapter: Custom `bedrock_client.py` added to the framework's LLM client factory

---

*Started May 20, 2026 with $10,000. Fully automated — no human intervention.*

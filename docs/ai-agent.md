---
layout: default
permalink: /ai-agent/
---

# AI Agent — Multi-Agent Trading Decisions

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

*Started May 20, 2026 with $10,000. Fully automated — no human intervention.*

---
layout: default
---

# Stock Intelligence

AI-powered daily stock screening and paper trading. Claude analyzes 2,700+ stocks every morning, picks the best swing trades, and tracks its own performance with real money simulation.

## Live Paper Trading — Two Strategies Competing

### Strategy A: Claude Single-Agent (since May 13)
![Equity Curve]({{ site.baseurl }}/assets/chart.svg)

*$10K → Claude picks 3-5 stocks daily, auto-exits at fib targets or stop losses.*

### Strategy B: [TradingAgents](https://github.com/TauricResearch/TradingAgents) Multi-Agent Debate (since May 20)

*$10K → Based on the open-source [TradingAgents](https://github.com/TauricResearch/TradingAgents) framework (77K+ stars, backed by academic research [arXiv:2412.20138](https://arxiv.org/abs/2412.20138)). Multiple AI agents — market analyst, fundamentals analyst, news analyst — independently analyze each stock, then debate bull vs. bear cases before a risk manager validates and a portfolio manager makes the final call. Same stocks as Strategy A, completely different decision process.*

{% include trading_agents_status.html %}

## How It Works

Every weekday at 9:45 AM ET:
1. **Screen** ~2,700 US stocks for momentum (above 50d EMA, positive weekly gain, market cap >$1B)
2. **Analyze** top 20 movers with fibonacci retracements, MACD, RSI, volume
3. **Claude picks** 3-5 best swing trades with entry, exit target, and stop loss
4. **WSB check** — compares retail sentiment against technicals
5. **Paper trade** — buys the picks, auto-exits when targets hit

## Latest Picks

{% assign sorted_daily = site.daily | sort: "date" | reverse %}
{% for post in sorted_daily limit:1 %}
### [{{ post.title }}]({{ post.url | relative_url }})
{{ post.excerpt }}
{% endfor %}

## Recent Daily Reports

{% assign sorted_daily = site.daily | sort: "date" | reverse %}
{% for post in sorted_daily limit:5 %}
- [{{ post.title }}]({{ post.url | relative_url }})
{% endfor %}

[See all daily reports →]({{ site.baseurl }}/archive/)

## Weekly Events

{% assign sorted_weekly = site.weekly | sort: "date" | reverse %}
{% for post in sorted_weekly limit:3 %}
- [{{ post.title }}]({{ post.url | relative_url }})
{% endfor %}

---

[View on GitHub](https://github.com/kai-ion/stock-intelligence) | [How It Works]({{ site.baseurl }}/about/)

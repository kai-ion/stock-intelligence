---
layout: home
title: Home
---

# Stock Intelligence

AI-powered daily stock screening and paper trading. Claude analyzes 2,700+ stocks every morning, picks the best swing trades, and tracks its own performance with real money simulation.

## Live Paper Trading Performance

![Equity Curve]({{ site.baseurl }}/assets/chart.svg)

*Started May 13, 2026 with $10,000. Buys Claude's top picks daily. Auto-exits at fibonacci targets or stop losses.*

## How It Works

Every weekday at 9:45 AM ET:
1. **Screen** ~2,700 US stocks for momentum (above 50d EMA, positive weekly gain, market cap >$1B)
2. **Analyze** top 20 movers with fibonacci retracements, MACD, RSI, volume
3. **Claude picks** 3-5 best swing trades with entry, exit target, and stop loss
4. **WSB check** — compares retail sentiment against technicals
5. **Paper trade** — buys the picks, auto-exits when targets hit

## Latest Picks

{% for post in site.daily limit:1 %}
### [{{ post.title }}]({{ post.url | relative_url }})
{{ post.excerpt }}
{% endfor %}

## Recent Daily Reports

{% for post in site.daily limit:7 %}
- [{{ post.title }}]({{ post.url | relative_url }})
{% endfor %}

## Weekly Events

{% for post in site.weekly limit:4 %}
- [{{ post.title }}]({{ post.url | relative_url }})
{% endfor %}

---

[View on GitHub](https://github.com/kai-ion/stock-intelligence) | [Methodology]({{ site.baseurl }}/about/)

---
layout: page
title: Performance
permalink: /performance/
---

# Paper Trading Performance

![Equity Curve]({{ site.baseurl }}/assets/chart.svg)

## Current Portfolio

{% include portfolio.html %}

## Rules

- Starting capital: $10,000
- 20% allocation per pick (max 5 positions)
- Auto-sells at fibonacci extension targets or stop losses
- Sells weakest position to fund new picks when capital is low
- Checked twice daily: morning (buy + exit check) and 3:55 PM (exit check)
- No manual intervention — fully automated

---

*Started May 13, 2026. Updated daily.*

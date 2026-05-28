#!/usr/bin/env python3
"""
Converts daily briefs and weekly reports into Jekyll blog posts.
Run after syncing results to generate/update the blog.
"""

import json
import os
import shutil
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent.parent
RESULTS_DIR = REPO_ROOT / "screener_output"
EVENTS_DIRS = [REPO_ROOT / "events" / "data", REPO_ROOT / "events"]
PAPER_TRADING_DIR = REPO_ROOT / "paper_trading"
DOCS_DIR = Path(__file__).parent
DAILY_DIR = DOCS_DIR / "_daily"
WEEKLY_DIR = DOCS_DIR / "_weekly"
ASSETS_DIR = DOCS_DIR / "assets"


def generate_daily_posts():
    """Convert _brief.md files into Jekyll posts."""
    DAILY_DIR.mkdir(exist_ok=True)

    if not RESULTS_DIR.exists():
        print("No results directory found")
        return

    for month_dir in sorted(RESULTS_DIR.iterdir()):
        if not month_dir.is_dir():
            continue
        for brief in sorted(month_dir.glob("*_brief.md")):
            date_str = brief.name.replace("_brief.md", "")
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue

            post_path = DAILY_DIR / f"{date_str}.md"

            # Read brief content
            content = brief.read_text()

            # Add Jekyll front matter
            front_matter = f"""---
layout: post
title: "Daily Report — {date.strftime('%B %d, %Y')}"
date: {date_str}
categories: daily
---

"""
            post_path.write_text(front_matter + content)

    print(f"Generated {len(list(DAILY_DIR.glob('*.md')))} daily posts")


def generate_weekly_posts():
    """Convert weekly reports into Jekyll posts."""
    WEEKLY_DIR.mkdir(exist_ok=True)

    # Find events directory (could be events/data/YYYY-MM/ or events/YYYY-MM/)
    all_reports = []
    for events_dir in EVENTS_DIRS:
        if not events_dir.exists():
            continue
        for month_dir in sorted(events_dir.iterdir()):
            if not month_dir.is_dir():
                continue
            all_reports.extend(month_dir.glob("week_*.md"))
        # Also check top-level .md files
        all_reports.extend(events_dir.glob("week_*.md"))

    for report in sorted(all_reports):
        date_str = report.name.replace("week_", "").replace(".md", "")
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        post_path = WEEKLY_DIR / f"{date_str}.md"

        content = report.read_text()

        front_matter = f"""---
layout: post
title: "Weekly Preview — Week of {date.strftime('%B %d, %Y')}"
date: {date_str}
categories: weekly
---

"""
        post_path.write_text(front_matter + content)

    print(f"Generated {len(list(WEEKLY_DIR.glob('*.md')))} weekly posts")


def generate_ai_agent_posts():
    """Convert TradingAgents daily reports into Jekyll posts."""
    ai_agent_dir = DOCS_DIR / "_ai_agent"
    ai_agent_dir.mkdir(exist_ok=True)

    # Check multiple possible locations for reports
    possible_dirs = [
        REPO_ROOT / "trading_agents" / "reports",
        REPO_ROOT / "trading_agents" / "data" / "reports",
    ]
    reports_dir = None
    for d in possible_dirs:
        if d.exists() and list(d.glob("*.md")):
            reports_dir = d
            break
    if not reports_dir:
        print("No AI Agent reports found")
        return

    for report in sorted(reports_dir.glob("*.md")):
        date_str = report.stem
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        post_path = ai_agent_dir / f"{date_str}.md"
        content = report.read_text()

        front_matter = f"""---
layout: post
title: "AI Agent Picks — {date.strftime('%B %d, %Y')}"
date: {date_str}
categories: ai-agent
---

"""
        post_path.write_text(front_matter + content)

    print(f"Generated {len(list(ai_agent_dir.glob('*.md')))} AI Agent posts")


def copy_assets():
    """Copy chart and other assets."""
    ASSETS_DIR.mkdir(exist_ok=True)

    chart_src = PAPER_TRADING_DIR / "chart.svg"
    if chart_src.exists():
        shutil.copy2(chart_src, ASSETS_DIR / "chart.svg")
        print("Copied chart.svg")


def generate_portfolio_include():
    """Generate portfolio HTML include from portfolio.json and latest snapshot."""
    includes_dir = DOCS_DIR / "_includes"
    includes_dir.mkdir(exist_ok=True)

    portfolio_file = PAPER_TRADING_DIR / "portfolio.json"
    if not portfolio_file.exists():
        (includes_dir / "portfolio.html").write_text("<p><em>No portfolio data available.</em></p>")
        return

    with open(portfolio_file) as f:
        portfolio = json.load(f)

    positions = portfolio.get("positions", {})
    cash = portfolio.get("cash", 0)
    starting = portfolio.get("starting_capital", 10000)

    # Get current values from latest snapshot
    snapshot_dir = PAPER_TRADING_DIR / "snapshots"
    current_values = {}
    if snapshot_dir.exists():
        all_snapshots = []
        for month_dir in sorted(snapshot_dir.iterdir()):
            if month_dir.is_dir():
                all_snapshots.extend(sorted(month_dir.glob("*.json")))
        if all_snapshots:
            with open(all_snapshots[-1]) as f:
                latest = json.load(f)
                current_values = latest.get("positions", {})

    if not positions:
        html = "<p><em>No open positions.</em></p>"
    else:
        total_value = cash
        html = '<table style="width:100%;border-collapse:collapse;font-size:14px;">\n'
        html += '<tr style="border-bottom:2px solid #ddd;"><th>Ticker</th><th>Shares</th><th>Entry</th><th>Current</th><th>P&L</th><th>Target</th><th>Stop</th></tr>\n'
        for ticker, pos in positions.items():
            entry_cost = pos["shares"] * pos["entry_price"]
            current_val = current_values.get(ticker, entry_cost)
            total_value += current_val
            pnl = current_val - entry_cost
            pnl_pct = (pnl / entry_cost) * 100 if entry_cost > 0 else 0
            current_price = current_val / pos["shares"] if pos["shares"] > 0 else 0

            color = "#16a34a" if pnl >= 0 else "#dc2626"
            html += f'<tr style="border-bottom:1px solid #eee;">'
            html += f'<td><strong>{ticker}</strong></td>'
            html += f'<td>{pos["shares"]:.2f}</td>'
            html += f'<td>${pos["entry_price"]:.2f}</td>'
            html += f'<td>${current_price:.2f}</td>'
            html += f'<td style="color:{color};font-weight:500;">${pnl:+,.2f} ({pnl_pct:+.1f}%)</td>'
            html += f'<td>${pos["exit_target"]:.2f}</td>'
            html += f'<td>${pos["stop_loss"]:.2f}</td>'
            html += f'</tr>\n'
        html += '</table>\n'

        total_return = (total_value - starting) / starting * 100
        color = "#16a34a" if total_return >= 0 else "#dc2626"
        html += f'<p style="margin-top:12px;font-size:16px;"><strong>Total Value: ${total_value:,.2f}</strong> <span style="color:{color};">({total_return:+.2f}%)</span></p>'
        html += f'<p style="color:#666;">Cash: ${cash:,.2f} | Positions: {len(positions)} | Started: ${starting:,.2f}</p>'

    (includes_dir / "portfolio.html").write_text(html)
    print("Generated portfolio include")


def main():
    print("Generating blog posts...")
    generate_daily_posts()
    generate_weekly_posts()
    generate_ai_agent_posts()
    copy_assets()
    generate_portfolio_include()
    print("Done!")


if __name__ == "__main__":
    main()

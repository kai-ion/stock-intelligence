#!/usr/bin/env python3
"""
Converts daily briefs and weekly reports into Jekyll blog posts.
Run after syncing results to generate/update the blog.
"""

import os
import shutil
from pathlib import Path
from datetime import datetime

RESULTS_DIR = Path(__file__).parent.parent / "results"
EVENTS_DIR = Path(__file__).parent.parent / "events" / "data"
PAPER_TRADING_DIR = Path(__file__).parent.parent / "paper_trading"
DOCS_DIR = Path(__file__).parent
DAILY_DIR = DOCS_DIR / "_daily"
WEEKLY_DIR = DOCS_DIR / "_weekly"
ASSETS_DIR = DOCS_DIR / "assets"


def generate_daily_posts():
    """Convert _brief.md files into Jekyll posts."""
    DAILY_DIR.mkdir(exist_ok=True)

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

    for month_dir in sorted(EVENTS_DIR.iterdir()):
        if not month_dir.is_dir():
            continue
        for report in sorted(month_dir.glob("week_*.md")):
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


def copy_assets():
    """Copy chart and other assets."""
    ASSETS_DIR.mkdir(exist_ok=True)

    chart_src = PAPER_TRADING_DIR / "chart.svg"
    if chart_src.exists():
        shutil.copy2(chart_src, ASSETS_DIR / "chart.svg")
        print("Copied chart.svg")


def main():
    print("Generating blog posts...")
    generate_daily_posts()
    generate_weekly_posts()
    copy_assets()
    print("Done!")


if __name__ == "__main__":
    main()

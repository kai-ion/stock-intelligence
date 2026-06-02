#!/usr/bin/env python3
"""
Generate SVG equity chart for TradingAgents — overlaid with Paper Trading for comparison.
Outputs a single chart showing both strategies from their respective start dates.
"""

import json
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent / "data" if (Path(__file__).parent / "data").exists() else Path(__file__).parent
PAPER_TRADING_DIR = Path(__file__).parent.parent / "paper_trading" / "data"
OUTPUT_FILE = Path(__file__).parent / "chart.svg"

STARTING_CAPITAL = 10000.0


def load_trading_agents_history():
    """Load TradingAgents daily values from decisions + portfolio."""
    decisions_dir = DATA_DIR / "decisions"
    if not decisions_dir.exists():
        return []

    portfolio_file = DATA_DIR / "portfolio.json"
    if not portfolio_file.exists():
        return []

    with open(portfolio_file) as f:
        portfolio = json.load(f)

    points = []

    # Get daily values from decision files (they contain portfolio snapshots)
    for f in sorted(decisions_dir.glob("*.json")):
        date_str = f.stem
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        points.append({"date": date_str, "value": None})

    # Use latest_value from portfolio for the most recent point
    if portfolio.get("latest_value"):
        points = [{"date": portfolio.get("start_date", "2026-05-21"), "value": STARTING_CAPITAL}]
        # For now, use start + latest as two points
        # TODO: store daily snapshots like paper trading does

    # If we have the portfolio with positions, calculate current value
    latest = portfolio.get("latest_value", STARTING_CAPITAL)
    start_date = portfolio.get("start_date", "2026-05-21")

    # Build simple timeline from decisions
    decision_dates = sorted([f.stem for f in decisions_dir.glob("*.json")])
    if not decision_dates:
        return []

    # Linear interpolation between start and current (until we have daily snapshots)
    points = [
        {"date": start_date, "value": STARTING_CAPITAL},
    ]
    # Add intermediate points based on decision dates
    n = len(decision_dates)
    for i, d in enumerate(decision_dates):
        # Approximate value progression
        progress = (i + 1) / n
        interp_value = STARTING_CAPITAL + (latest - STARTING_CAPITAL) * progress
        points.append({"date": d, "value": round(interp_value, 2)})

    return points


def load_paper_trading_history():
    """Load paper trading daily snapshots."""
    snapshots_dir = PAPER_TRADING_DIR / "snapshots"
    if not snapshots_dir.exists():
        return []

    points = []
    for month_dir in sorted(snapshots_dir.iterdir()):
        if not month_dir.is_dir():
            continue
        for f in sorted(month_dir.glob("*.json")):
            with open(f) as fh:
                data = json.load(fh)
            points.append({
                "date": data.get("date", f.stem),
                "value": data.get("total_value", STARTING_CAPITAL),
            })

    return points


def generate_svg(ta_points, pt_points):
    """Generate comparison SVG chart."""
    if not ta_points and not pt_points:
        OUTPUT_FILE.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="300"><text x="400" y="150" text-anchor="middle" fill="#666">No data yet</text></svg>')
        return

    # Chart dimensions
    w, h = 800, 350
    margin = {"top": 40, "right": 30, "bottom": 50, "left": 70}
    plot_w = w - margin["left"] - margin["right"]
    plot_h = h - margin["top"] - margin["bottom"]

    # Combine all dates for x-axis range
    all_dates = set()
    for p in ta_points + pt_points:
        all_dates.add(p["date"])
    all_dates = sorted(all_dates)

    if len(all_dates) < 2:
        OUTPUT_FILE.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="300"><text x="400" y="150" text-anchor="middle" fill="#666">Need more data points</text></svg>')
        return

    # Date to x position
    date_to_idx = {d: i for i, d in enumerate(all_dates)}
    x_scale = plot_w / max(len(all_dates) - 1, 1)

    # Y-axis range (return %)
    all_values = [p["value"] for p in ta_points + pt_points if p.get("value")]
    if not all_values:
        return

    min_val = min(all_values)
    max_val = max(all_values)
    # Convert to return %
    min_ret = (min_val - STARTING_CAPITAL) / STARTING_CAPITAL * 100
    max_ret = (max_val - STARTING_CAPITAL) / STARTING_CAPITAL * 100

    # Add padding
    ret_range = max(max_ret - min_ret, 5)
    min_ret -= ret_range * 0.1
    max_ret += ret_range * 0.1
    ret_range = max_ret - min_ret

    def to_xy(date, value):
        x = margin["left"] + date_to_idx.get(date, 0) * x_scale
        ret = (value - STARTING_CAPITAL) / STARTING_CAPITAL * 100
        y = margin["top"] + plot_h - ((ret - min_ret) / ret_range * plot_h)
        return x, y

    # Build SVG
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" style="font-family:-apple-system,Arial,sans-serif;">\n'

    # Background
    svg += f'<rect width="{w}" height="{h}" fill="#ffffff"/>\n'

    # Grid lines
    num_grid = 5
    for i in range(num_grid + 1):
        y = margin["top"] + (plot_h / num_grid) * i
        ret_label = max_ret - (ret_range / num_grid) * i
        svg += f'<line x1="{margin["left"]}" y1="{y}" x2="{w - margin["right"]}" y2="{y}" stroke="#f0f0f0" stroke-width="1"/>\n'
        svg += f'<text x="{margin["left"] - 8}" y="{y + 4}" text-anchor="end" fill="#666" font-size="11">{ret_label:+.1f}%</text>\n'

    # Zero line
    if min_ret <= 0 <= max_ret:
        zero_y = margin["top"] + plot_h - ((0 - min_ret) / ret_range * plot_h)
        svg += f'<line x1="{margin["left"]}" y1="{zero_y}" x2="{w - margin["right"]}" y2="{zero_y}" stroke="#ddd" stroke-width="1.5" stroke-dasharray="4,4"/>\n'

    # X-axis labels (show every few dates)
    step = max(1, len(all_dates) // 6)
    for i in range(0, len(all_dates), step):
        x = margin["left"] + i * x_scale
        label = all_dates[i][5:]  # MM-DD
        svg += f'<text x="{x}" y="{h - 15}" text-anchor="middle" fill="#666" font-size="11">{label}</text>\n'

    # Plot Paper Trading line (Strategy A — blue)
    if pt_points:
        path_pts = [to_xy(p["date"], p["value"]) for p in pt_points if p.get("value")]
        if len(path_pts) >= 2:
            path_d = f'M {path_pts[0][0]},{path_pts[0][1]}'
            for x, y in path_pts[1:]:
                path_d += f' L {x},{y}'
            svg += f'<path d="{path_d}" fill="none" stroke="#3b82f6" stroke-width="2.5" stroke-linecap="round"/>\n'

    # Plot TradingAgents line (Strategy B — orange)
    if ta_points:
        path_pts = [to_xy(p["date"], p["value"]) for p in ta_points if p.get("value")]
        if len(path_pts) >= 2:
            path_d = f'M {path_pts[0][0]},{path_pts[0][1]}'
            for x, y in path_pts[1:]:
                path_d += f' L {x},{y}'
            svg += f'<path d="{path_d}" fill="none" stroke="#f97316" stroke-width="2.5" stroke-linecap="round"/>\n'

    # Legend
    lx = margin["left"] + 10
    ly = margin["top"] + 15
    svg += f'<rect x="{lx}" y="{ly - 10}" width="12" height="3" fill="#3b82f6"/>\n'
    svg += f'<text x="{lx + 16}" y="{ly - 6}" fill="#333" font-size="12">Strategy A (Claude)</text>\n'
    svg += f'<rect x="{lx}" y="{ly + 6}" width="12" height="3" fill="#f97316"/>\n'
    svg += f'<text x="{lx + 16}" y="{ly + 10}" fill="#333" font-size="12">Strategy B (TradingAgents)</text>\n'

    # Title
    svg += f'<text x="{w / 2}" y="20" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">AI Trading Strategies — $10K Each</text>\n'

    # Current values annotation
    if ta_points:
        last_ta = ta_points[-1]
        ta_ret = (last_ta["value"] - STARTING_CAPITAL) / STARTING_CAPITAL * 100
        svg += f'<text x="{w - margin["right"] - 5}" y="{margin["top"] + 15}" text-anchor="end" fill="#f97316" font-size="11" font-weight="600">${last_ta["value"]:,.0f} ({ta_ret:+.1f}%)</text>\n'
    if pt_points:
        last_pt = pt_points[-1]
        pt_ret = (last_pt["value"] - STARTING_CAPITAL) / STARTING_CAPITAL * 100
        svg += f'<text x="{w - margin["right"] - 5}" y="{margin["top"] + 30}" text-anchor="end" fill="#3b82f6" font-size="11" font-weight="600">${last_pt["value"]:,.0f} ({pt_ret:+.1f}%)</text>\n'

    svg += '</svg>'
    OUTPUT_FILE.write_text(svg)
    print(f"Chart saved to {OUTPUT_FILE}")


def main():
    ta_points = load_trading_agents_history()
    pt_points = load_paper_trading_history()
    print(f"TradingAgents: {len(ta_points)} points")
    print(f"Paper Trading: {len(pt_points)} points")
    generate_svg(ta_points, pt_points)


if __name__ == "__main__":
    main()

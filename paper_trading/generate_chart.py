#!/usr/bin/env python3
"""
Generate an SVG equity curve chart for Claude's paper trading performance.
Outputs to paper_trading/chart.svg — viewable directly on GitHub.
"""

import json
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_FILE = Path(__file__).parent / "chart.svg"


def load_snapshots():
    snapshots = []
    snap_dir = DATA_DIR / "snapshots"
    if snap_dir.exists():
        for month_dir in sorted(snap_dir.iterdir()):
            if not month_dir.is_dir():
                continue
            for f in sorted(month_dir.glob("*.json")):
                with open(f) as fh:
                    snapshots.append(json.load(fh))
    return snapshots


def load_all_trades():
    trades = []
    history_dir = DATA_DIR / "history"
    if history_dir.exists():
        for year_dir in sorted(history_dir.iterdir()):
            if not year_dir.is_dir():
                continue
            for month_dir in sorted(year_dir.iterdir()):
                if not month_dir.is_dir():
                    continue
                for day_file in sorted(month_dir.glob("*.json")):
                    with open(day_file) as fh:
                        trades.extend(json.load(fh))
    return trades


def generate_svg(snapshots, trades):
    starting = 10000
    if not snapshots:
        snapshots = [{"date": datetime.now().strftime("%Y-%m-%d"), "total_value": starting}]

    values = [s["total_value"] for s in snapshots]
    dates = [s["date"] for s in snapshots]

    # Chart dimensions
    width = 800
    height = 400
    padding_left = 70
    padding_right = 30
    padding_top = 60
    padding_bottom = 80

    chart_w = width - padding_left - padding_right
    chart_h = height - padding_top - padding_bottom

    # Scale
    min_val = min(min(values), starting) * 0.95
    max_val = max(max(values), starting) * 1.05
    val_range = max_val - min_val if max_val != min_val else 1

    # Stats
    current_value = values[-1]
    total_return = (current_value - starting) / starting * 100
    sells = [t for t in trades if t["action"] == "SELL"]
    wins = sum(1 for t in sells if t.get("pnl", 0) > 0)
    win_rate = f"{wins}/{len(sells)} ({wins/len(sells)*100:.0f}%)" if sells else "0/0"
    realized_pnl = sum(t.get("pnl", 0) for t in sells)

    # Colors
    line_color = "#16a34a" if current_value >= starting else "#dc2626"
    bg_color = "#0d1117"
    grid_color = "#21262d"
    text_color = "#c9d1d9"
    accent = "#58a6ff"

    def x_pos(i):
        if len(values) == 1:
            return padding_left + chart_w / 2
        return padding_left + (i / (len(values) - 1)) * chart_w

    def y_pos(v):
        return padding_top + chart_h - ((v - min_val) / val_range) * chart_h

    # Build path
    points = [(x_pos(i), y_pos(v)) for i, v in enumerate(values)]
    path_d = f"M {points[0][0]:.1f} {points[0][1]:.1f}"
    for x, y in points[1:]:
        path_d += f" L {x:.1f} {y:.1f}"

    # Fill area under curve
    fill_d = path_d + f" L {points[-1][0]:.1f} {padding_top + chart_h:.1f} L {points[0][0]:.1f} {padding_top + chart_h:.1f} Z"

    # Baseline (starting capital)
    baseline_y = y_pos(starting)

    # Y-axis labels
    y_labels = []
    num_y_labels = 5
    for i in range(num_y_labels + 1):
        val = min_val + (val_range * i / num_y_labels)
        y = y_pos(val)
        y_labels.append((y, f"${val:,.0f}"))

    # X-axis labels (show first, last, and middle dates)
    x_labels = []
    if len(dates) >= 3:
        indices = [0, len(dates) // 2, len(dates) - 1]
    elif len(dates) == 2:
        indices = [0, 1]
    else:
        indices = [0]
    for i in indices:
        x_labels.append((x_pos(i), dates[i]))

    # Trade markers
    trade_markers = ""
    for t in sells:
        trade_date = t.get("date", "")
        if trade_date in dates:
            idx = dates.index(trade_date)
            tx = x_pos(idx)
            ty = y_pos(values[idx])
            color = "#16a34a" if t.get("pnl", 0) > 0 else "#dc2626"
            trade_markers += f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="4" fill="{color}" opacity="0.8"/>\n'

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
  <rect width="{width}" height="{height}" fill="{bg_color}" rx="8"/>

  <!-- Title -->
  <text x="{padding_left}" y="30" fill="{text_color}" font-family="system-ui, -apple-system, sans-serif" font-size="16" font-weight="bold">Claude's Paper Trading — Equity Curve</text>
  <text x="{padding_left}" y="48" fill="{accent}" font-family="system-ui, sans-serif" font-size="12">
    ${current_value:,.2f} ({total_return:+.2f}%) | Win Rate: {win_rate} | Realized: ${realized_pnl:+,.2f}
  </text>

  <!-- Grid lines -->
  {"".join(f'<line x1="{padding_left}" y1="{y:.1f}" x2="{width - padding_right}" y2="{y:.1f}" stroke="{grid_color}" stroke-width="0.5"/>' for y, _ in y_labels)}

  <!-- Baseline (starting capital) -->
  <line x1="{padding_left}" y1="{baseline_y:.1f}" x2="{width - padding_right}" y2="{baseline_y:.1f}" stroke="{text_color}" stroke-width="0.5" stroke-dasharray="4,4" opacity="0.5"/>
  <text x="{width - padding_right + 5}" y="{baseline_y:.1f}" fill="{text_color}" font-size="9" opacity="0.6" dominant-baseline="middle">$10K</text>

  <!-- Fill under curve -->
  <path d="{fill_d}" fill="{line_color}" opacity="0.1"/>

  <!-- Equity line -->
  <path d="{path_d}" fill="none" stroke="{line_color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>

  <!-- Data points -->
  {"".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{line_color}"/>' for x, y in points)}

  <!-- Trade markers -->
  {trade_markers}

  <!-- Y-axis labels -->
  {"".join(f'<text x="{padding_left - 8}" y="{y:.1f}" fill="{text_color}" font-size="10" text-anchor="end" dominant-baseline="middle">{label}</text>' for y, label in y_labels)}

  <!-- X-axis labels -->
  {"".join(f'<text x="{x:.1f}" y="{height - padding_bottom + 20}" fill="{text_color}" font-size="10" text-anchor="middle">{label}</text>' for x, label in x_labels)}

  <!-- Legend -->
  <circle cx="{width - 150}" cy="{height - 20}" r="4" fill="#16a34a"/>
  <text x="{width - 142}" y="{height - 16}" fill="{text_color}" font-size="9">Win</text>
  <circle cx="{width - 110}" cy="{height - 20}" r="4" fill="#dc2626"/>
  <text x="{width - 102}" y="{height - 16}" fill="{text_color}" font-size="9">Loss</text>
  <line x1="{width - 70}" y1="{height - 20}" x2="{width - 55}" y2="{height - 20}" stroke="{text_color}" stroke-width="0.5" stroke-dasharray="4,4" opacity="0.5"/>
  <text x="{width - 50}" y="{height - 16}" fill="{text_color}" font-size="9">$10K baseline</text>
</svg>"""

    with open(OUTPUT_FILE, "w") as f:
        f.write(svg)
    print(f"Chart saved to {OUTPUT_FILE}")


def main():
    snapshots = load_snapshots()
    trades = load_all_trades()
    generate_svg(snapshots, trades)


if __name__ == "__main__":
    main()

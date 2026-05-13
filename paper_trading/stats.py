#!/usr/bin/env python3
"""
View Claude's paper trading performance.

Usage:
  python3 stats.py              # Current portfolio + all-time stats
  python3 stats.py --trades     # Show recent trade history
  python3 stats.py --curve      # Show daily equity curve
"""

import json
import argparse
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"


def load_portfolio():
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE) as f:
            return json.load(f)
    return None


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
                    with open(day_file) as f:
                        trades.extend(json.load(f))
    return trades


def load_snapshots():
    snapshots = []
    snap_dir = DATA_DIR / "snapshots"
    if snap_dir.exists():
        for year_dir in sorted(snap_dir.iterdir()):
            if not year_dir.is_dir():
                continue
            for month_dir in sorted(year_dir.iterdir()):
                if not month_dir.is_dir():
                    continue
                for f in sorted(month_dir.glob("*.json")):
                    with open(f) as fh:
                        snapshots.append(json.load(fh))
    return snapshots


def show_portfolio(portfolio):
    if not portfolio:
        print("No portfolio data found. Run sync_results.sh first.")
        return

    starting = portfolio.get("starting_capital", 10000)
    cash = portfolio.get("cash", 0)
    positions = portfolio.get("positions", {})

    print(f"\n{'='*60}")
    print(f"  CLAUDE'S PAPER TRADING PORTFOLIO")
    print(f"{'='*60}")
    print(f"  Started: {portfolio.get('start_date', '?')} with ${starting:,.2f}")
    print(f"{'='*60}\n")

    if positions:
        print(f"  {'Ticker':<8} {'Shares':<8} {'Entry':<10} {'Target':<10} {'Stop':<10} {'Date':<12}")
        print(f"  {'-'*58}")
        for ticker, pos in positions.items():
            print(f"  {ticker:<8} {pos['shares']:<8.2f} ${pos['entry_price']:<9.2f} ${pos['exit_target']:<9.2f} ${pos['stop_loss']:<9.2f} {pos['entry_date']}")
    else:
        print("  No open positions.")

    print(f"\n  Cash: ${cash:,.2f}")


def show_stats(trades):
    if not trades:
        print("\nNo trade history found.")
        return

    buys = [t for t in trades if t["action"] == "BUY"]
    sells = [t for t in trades if t["action"] == "SELL"]
    wins = [t for t in sells if t.get("pnl", 0) > 0]
    losses = [t for t in sells if t.get("pnl", 0) <= 0]

    total_realized = sum(t.get("pnl", 0) for t in sells)
    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
    avg_hold = sum(t.get("hold_days", 0) for t in sells) / len(sells) if sells else 0

    target_hits = [t for t in sells if t.get("reason") == "TARGET HIT"]
    stop_hits = [t for t in sells if t.get("reason") == "STOP LOSS"]
    replaced = [t for t in sells if "REPLACED" in t.get("reason", "")]

    print(f"\n{'='*60}")
    print(f"  ALL-TIME STATS")
    print(f"{'='*60}")
    print(f"  Total trades:     {len(buys)} buys, {len(sells)} sells")
    print(f"  Win rate:         {len(wins)}/{len(sells)} ({len(wins)/len(sells)*100:.0f}%)" if sells else "  Win rate:         N/A")
    print(f"  Realized P&L:     ${total_realized:+,.2f}")
    print(f"  Avg win:          ${avg_win:+,.2f}")
    print(f"  Avg loss:         ${avg_loss:+,.2f}")
    print(f"  Avg hold (days):  {avg_hold:.1f}")
    print(f"\n  Exit reasons:")
    print(f"    Target hit:     {len(target_hits)}")
    print(f"    Stop loss:      {len(stop_hits)}")
    print(f"    Replaced:       {len(replaced)}")
    print()


def show_trades(trades, n=20):
    if not trades:
        print("\nNo trade history found.")
        return

    print(f"\n  {'Date':<12} {'Action':<10} {'Ticker':<8} {'Price':<10} {'P&L':<12} {'Reason'}")
    print(f"  {'-'*70}")
    for t in trades[-n:]:
        pnl = f"${t.get('pnl', 0):+.2f}" if t["action"] == "SELL" else ""
        reason = t.get("reason", "")[:25] if t["action"] == "SELL" else t.get("reasoning", {}).get("upside", "")[:25]
        print(f"  {t['date']:<12} {t['action']:<10} {t['ticker']:<8} ${t['price']:<9.2f} {pnl:<12} {reason}")
    print()


def show_curve(snapshots):
    if not snapshots:
        print("\nNo snapshots found.")
        return

    starting = 10000
    print(f"\n  {'Date':<12} {'Value':<12} {'Return':<10} {'Positions'}")
    print(f"  {'-'*50}")
    for s in snapshots:
        value = s["total_value"]
        ret = (value - starting) / starting * 100
        positions = ", ".join(s.get("positions", {}).keys())
        bar = "+" * int(max(0, ret)) + "-" * int(max(0, -ret))
        print(f"  {s['date']:<12} ${value:<11,.2f} {ret:+7.2f}%  {positions}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Claude paper trading stats")
    parser.add_argument("--trades", action="store_true", help="Show recent trades")
    parser.add_argument("--curve", action="store_true", help="Show equity curve")
    parser.add_argument("-n", type=int, default=20, help="Number of trades to show")
    args = parser.parse_args()

    portfolio = load_portfolio()
    trades = load_all_trades()
    snapshots = load_snapshots()

    if args.trades:
        show_trades(trades, args.n)
    elif args.curve:
        show_curve(snapshots)
    else:
        show_portfolio(portfolio)
        show_stats(trades)


if __name__ == "__main__":
    main()

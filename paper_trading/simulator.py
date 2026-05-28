#!/usr/bin/env python3
"""
Paper Trading Simulator — tracks Claude's picks performance.
Buys at the price recommended, sells when exit target is hit or stop loss triggers.
Starts with $10,000 budget.
"""

import json
import re
import os
import yfinance as yf
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"
RESULTS_DIR = Path(__file__).parent.parent / "screener_output"
STARTING_CAPITAL = 10000.0


def get_history_file():
    """Get path to current month's trade history file."""
    date_str = datetime.now().strftime("%Y/%m/%d")
    history_dir = DATA_DIR / "history" / datetime.now().strftime("%Y/%m")
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir / f"{datetime.now().strftime('%d')}.json"


def load_portfolio():
    """Load current paper trading portfolio."""
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE) as f:
            return json.load(f)
    return {
        "cash": STARTING_CAPITAL,
        "positions": {},
        "start_date": datetime.now().strftime("%Y-%m-%d"),
        "starting_capital": STARTING_CAPITAL,
    }


def save_portfolio(portfolio):
    """Save portfolio state locally and to S3."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(portfolio, f, indent=2)


def save_trade_history(history):
    """Save today's trades to daily history file."""
    history_file = get_history_file()
    history_file.parent.mkdir(parents=True, exist_ok=True)
    with open(history_file, "w") as f:
        json.dump(history, f, indent=2)


def sync_to_s3(portfolio, history):
    """Upload portfolio state and daily snapshot to S3."""
    import boto3
    bucket = os.environ.get("S3_BUCKET", "")
    if not bucket:
        return

    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    date_str = datetime.now().strftime("%Y-%m-%d")
    month_str = datetime.now().strftime("%Y-%m")

    # Upload current state (overwritten each run)
    s3.put_object(
        Bucket=bucket,
        Key="paper_trading/portfolio.json",
        Body=json.dumps(portfolio, indent=2).encode()
    )

    # Upload today's trade history
    date_now = datetime.now()
    history_key = f"paper_trading/history/{date_now.strftime('%Y/%m/%d')}.json"
    s3.put_object(
        Bucket=bucket,
        Key=history_key,
        Body=json.dumps(history, indent=2).encode()
    )

    # Save daily snapshot (equity curve tracking)
    total_value = portfolio["cash"] + sum(
        (get_current_price(t) or pos["entry_price"]) * pos["shares"]
        for t, pos in portfolio["positions"].items()
    )
    snapshot = {
        "date": date_str,
        "total_value": round(total_value, 2),
        "cash": round(portfolio["cash"], 2),
        "positions_count": len(portfolio["positions"]),
        "positions": {t: round((get_current_price(t) or p["entry_price"]) * p["shares"], 2)
                      for t, p in portfolio["positions"].items()},
    }
    s3.put_object(
        Bucket=bucket,
        Key=f"paper_trading/snapshots/{month_str}/{date_str}.json",
        Body=json.dumps(snapshot, indent=2).encode()
    )
    print(f"  Synced to S3 (value: ${total_value:,.2f})")


def load_trade_history():
    """Load today's trade history."""
    history_file = get_history_file()
    if history_file.exists():
        with open(history_file) as f:
            return json.load(f)
    return []


def load_all_trade_history():
    """Load all trade history across all days (for stats)."""
    all_trades = []
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
                        all_trades.extend(json.load(f))
    return all_trades


def parse_picks_from_brief(brief_path):
    """Extract Claude's picks with entry price and exit target from a brief."""
    with open(brief_path) as f:
        content = f.read()

    picks = []

    # Find Top Movers section for price/target data
    movers_section = re.search(r"## Top Movers(.*?)## Headlines", content, re.DOTALL)
    movers_data = {}
    if movers_section:
        # Parse each mover: **TICKER** (+X.X%) — $PRICE → $TARGET (+Y.Y% upside)
        mover_pattern = re.compile(
            r'\*\*(\w+)\*\*.*?\$(\d+[\d,.]*)\s*→\s*\$(\d+[\d,.]*)\s*\(\+?([\d.]+)%'
        )
        for m in mover_pattern.finditer(movers_section.group(1)):
            ticker = m.group(1)
            entry = float(m.group(2).replace(",", ""))
            target = float(m.group(3).replace(",", ""))
            upside = float(m.group(4))
            movers_data[ticker] = {"entry": entry, "target": target, "upside": upside}

    # Find Claude's Top Picks section
    picks_section = re.search(r"## Claude's Top Picks(.*?)## Avoid", content, re.DOTALL)
    if not picks_section:
        picks_section = re.search(r"## Claude's Top Picks(.*?)$", content, re.DOTALL)
    if not picks_section:
        return []

    # Extract ticker names and reasoning from picks
    # Parse: **TICKER** ... \nUpside: ...\nRisk: ...
    pick_blocks = re.split(r'\*\*([A-Z]+)\*\*', picks_section.group(1))
    pick_reasoning = {}
    for i in range(1, len(pick_blocks) - 1, 2):
        ticker = pick_blocks[i]
        block = pick_blocks[i + 1]
        upside_match = re.search(r'Upside:\s*(.+?)(?:\n|$)', block)
        risk_match = re.search(r'Risk:\s*(.+?)(?:\n|$)', block)
        pick_reasoning[ticker] = {
            "upside": upside_match.group(1).strip() if upside_match else "",
            "risk": risk_match.group(1).strip() if risk_match else "",
        }

    pick_tickers = list(pick_reasoning.keys())

    for ticker in pick_tickers:
        if ticker in movers_data:
            picks.append({
                "ticker": ticker,
                "entry_price": movers_data[ticker]["entry"],
                "exit_target": movers_data[ticker]["target"],
                "upside_pct": movers_data[ticker]["upside"],
                "reasoning": pick_reasoning.get(ticker, {}),
            })

    # Also try parsing exit target directly from picks section
    # Format: **TICKER** (+X.X% today, +Y.Y% week) — $CURRENT → $EXIT (+Z.Z% upside)
    pick_pattern = re.compile(
        r'\*\*(\w+)\*\*.*?\$(\d+[\d,.]*)\s*→\s*\$(\d+[\d,.]*)\s*\(\+?([\d.]+)%'
    )
    for m in pick_pattern.finditer(picks_section.group(1)):
        ticker = m.group(1)
        if not any(p["ticker"] == ticker for p in picks):
            picks.append({
                "ticker": ticker,
                "entry_price": float(m.group(2).replace(",", "")),
                "exit_target": float(m.group(3).replace(",", "")),
                "upside_pct": float(m.group(4)),
                "reasoning": pick_reasoning.get(ticker, {}),
            })

    # Parse support/stop from the movers section for stop loss
    for pick in picks:
        ticker = pick["ticker"]
        support_pattern = re.compile(
            rf'\*\*{ticker}\*\*.*?Support.*?\$(\d+[\d,.]*)', re.DOTALL
        )
        support_match = support_pattern.search(content)
        if support_match:
            pick["stop_loss"] = float(support_match.group(1).replace(",", ""))
        else:
            # Default stop loss: 10% below entry
            pick["stop_loss"] = pick["entry_price"] * 0.90

    return picks


def get_current_price(ticker):
    """Get current price from yfinance."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def free_up_capital(portfolio, history, needed):
    """Sell the weakest position to free up capital for new picks."""
    if not portfolio["positions"]:
        return

    # Rank positions by current P&L % (sell the worst performer)
    ranked = []
    for ticker, pos in portfolio["positions"].items():
        price = get_current_price(ticker)
        if price is None:
            price = pos["entry_price"]
        pnl_pct = (price - pos["entry_price"]) / pos["entry_price"] * 100
        ranked.append((ticker, price, pnl_pct))

    ranked.sort(key=lambda x: x[2])  # worst first

    # Sell weakest positions until we have enough cash
    for ticker, price, pnl_pct in ranked:
        if portfolio["cash"] >= needed:
            break

        pos = portfolio["positions"][ticker]
        proceeds = pos["shares"] * price
        pnl = proceeds - pos["cost"]

        portfolio["cash"] += proceeds
        history.append({
            "action": "SELL",
            "ticker": ticker,
            "shares": pos["shares"],
            "price": round(price, 2),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "reason": "REPLACED (weakest position sold for new pick)",
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "entry_price": pos["entry_price"],
            "hold_days": (datetime.now() - datetime.strptime(pos["entry_date"], "%Y-%m-%d")).days,
        })
        print(f"  SELL {ticker} (weakest): {pos['shares']:.2f} shares @ ${price:.2f} P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%) → freeing capital for new pick")
        del portfolio["positions"][ticker]
        break  # only sell one at a time


def buy_picks(portfolio, picks, history):
    """Buy Claude's picks with equal allocation from available cash."""
    if not picks:
        return

    # Filter out picks we already hold
    new_picks = [p for p in picks if p["ticker"] not in portfolio["positions"]]
    if not new_picks:
        print("  Already holding all picks. No new buys.")
        return

    # Calculate allocation
    total_value = portfolio["cash"] + sum(
        (get_current_price(t) or pos["entry_price"]) * pos["shares"]
        for t, pos in portfolio["positions"].items()
    )
    allocation_per_pick = total_value * 0.20  # 20% per position

    for pick in new_picks:
        # If not enough cash, sell weakest to fund
        if portfolio["cash"] < allocation_per_pick * 0.5 and portfolio["positions"]:
            print(f"\n  Low cash (${portfolio['cash']:.2f}). Selling weakest to fund {pick['ticker']}...")
            free_up_capital(portfolio, history, allocation_per_pick)

        if portfolio["cash"] < 100:
            print(f"  SKIP {pick['ticker']}: insufficient cash (${portfolio['cash']:.2f})")
            continue

        cost = min(allocation_per_pick, portfolio["cash"])
        shares = cost / pick["entry_price"]
        cost = shares * pick["entry_price"]

        portfolio["positions"][pick["ticker"]] = {
            "shares": round(shares, 4),
            "entry_price": pick["entry_price"],
            "exit_target": pick["exit_target"],
            "stop_loss": pick["stop_loss"],
            "entry_date": datetime.now().strftime("%Y-%m-%d"),
            "cost": round(cost, 2),
        }
        portfolio["cash"] -= cost

        history.append({
            "action": "BUY",
            "ticker": pick["ticker"],
            "shares": round(shares, 4),
            "price": pick["entry_price"],
            "date": datetime.now().strftime("%Y-%m-%d"),
            "target": pick["exit_target"],
            "stop": pick["stop_loss"],
            "reasoning": pick.get("reasoning", {}),
        })
        print(f"  BUY {pick['ticker']}: {shares:.2f} shares @ ${pick['entry_price']:.2f} (target: ${pick['exit_target']:.2f})")


def check_exits(portfolio, history):
    """Check if any positions hit exit target or stop loss."""
    to_sell = []

    for ticker, pos in portfolio["positions"].items():
        price = get_current_price(ticker)
        if price is None:
            continue

        if price >= pos["exit_target"]:
            to_sell.append((ticker, price, "TARGET HIT"))
        elif price <= pos["stop_loss"]:
            to_sell.append((ticker, price, "STOP LOSS"))

    for ticker, price, reason in to_sell:
        pos = portfolio["positions"][ticker]
        proceeds = pos["shares"] * price
        pnl = proceeds - pos["cost"]
        pnl_pct = (price - pos["entry_price"]) / pos["entry_price"] * 100

        portfolio["cash"] += proceeds
        history.append({
            "action": "SELL",
            "ticker": ticker,
            "shares": pos["shares"],
            "price": round(price, 2),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "reason": reason,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "entry_price": pos["entry_price"],
            "hold_days": (datetime.now() - datetime.strptime(pos["entry_date"], "%Y-%m-%d")).days,
        })
        print(f"  SELL {ticker}: {pos['shares']:.2f} shares @ ${price:.2f} ({reason}) P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)")

    for ticker, _, _ in to_sell:
        del portfolio["positions"][ticker]


def print_summary(portfolio, history):
    """Print portfolio summary."""
    total_unrealized = 0
    print(f"\n{'='*60}")
    print(f"  CLAUDE'S PAPER TRADING PORTFOLIO")
    print(f"{'='*60}")
    print(f"  Started: {portfolio.get('start_date', 'N/A')} with ${portfolio['starting_capital']:,.2f}")
    print(f"{'='*60}\n")

    if portfolio["positions"]:
        print(f"  {'Ticker':<8} {'Shares':<8} {'Entry':<10} {'Current':<10} {'P&L':<12} {'Target':<10} {'Stop':<10}")
        print(f"  {'-'*68}")
        for ticker, pos in portfolio["positions"].items():
            price = get_current_price(ticker)
            if price is None:
                price = pos["entry_price"]
            pnl = (price - pos["entry_price"]) * pos["shares"]
            pnl_pct = (price - pos["entry_price"]) / pos["entry_price"] * 100
            total_unrealized += pnl
            print(f"  {ticker:<8} {pos['shares']:<8.2f} ${pos['entry_price']:<9.2f} ${price:<9.2f} ${pnl:<+11.2f} ${pos['exit_target']:<9.2f} ${pos['stop_loss']:<9.2f}")
    else:
        print("  No open positions.\n")

    position_value = sum(
        (get_current_price(t) or pos["entry_price"]) * pos["shares"]
        for t, pos in portfolio["positions"].items()
    )
    total_value = portfolio["cash"] + position_value
    total_return = (total_value - portfolio["starting_capital"]) / portfolio["starting_capital"] * 100

    # Realized P&L from ALL history
    all_history = load_all_trade_history()
    realized = sum(t.get("pnl", 0) for t in all_history if t["action"] == "SELL")
    wins = sum(1 for t in all_history if t["action"] == "SELL" and t.get("pnl", 0) > 0)
    losses = sum(1 for t in all_history if t["action"] == "SELL" and t.get("pnl", 0) <= 0)

    print(f"\n  Cash:           ${portfolio['cash']:>10,.2f}")
    print(f"  Positions:      ${position_value:>10,.2f}")
    print(f"  Total Value:    ${total_value:>10,.2f}")
    print(f"  Total Return:   {total_return:>+9.2f}%")
    print(f"\n  Realized P&L:   ${realized:>+10,.2f}")
    print(f"  Unrealized P&L: ${total_unrealized:>+10,.2f}")
    print(f"  Win/Loss:       {wins}W / {losses}L")
    print()


def main():
    print(f"=== Paper Trading Simulator — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    portfolio = load_portfolio()
    history = load_trade_history()

    # Check for exits on existing positions
    if portfolio["positions"]:
        print("Checking exit targets and stop losses...")
        check_exits(portfolio, history)

    # Parse today's picks from brief
    date_str = datetime.now().strftime("%Y-%m-%d")
    month_str = datetime.now().strftime("%Y-%m")
    brief_path = RESULTS_DIR / month_str / f"{date_str}_brief.md"

    if brief_path.exists():
        print(f"\nParsing today's picks from {brief_path.name}...")
        picks = parse_picks_from_brief(brief_path)
        if picks:
            print(f"  Found {len(picks)} picks: {', '.join(p['ticker'] for p in picks)}")
            buy_picks(portfolio, picks, history)
        else:
            print("  No picks found in today's brief.")
    else:
        print(f"  No brief found for {date_str}.")

    # Save state
    save_portfolio(portfolio)
    save_trade_history(history)

    # Sync to S3 for backup and local access
    sync_to_s3(portfolio, history)

    # Print summary
    print_summary(portfolio, history)


if __name__ == "__main__":
    main()

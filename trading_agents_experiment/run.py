#!/usr/bin/env python3
"""
TradingAgents Paper Trading Experiment
Runs the multi-agent debate framework on the same tickers as our screener picks.
Separate $10K portfolio to compare against Claude's single-agent picks.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tradingagents", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = Path(__file__).parent / "data"
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"
RESULTS_DIR = Path(__file__).parent.parent / "results"
STARTING_CAPITAL = 10000.0


def load_portfolio():
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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(portfolio, f, indent=2)


def get_todays_tickers():
    """Get today's top movers from the screener CSV."""
    import pandas as pd
    date_str = datetime.now().strftime("%Y-%m-%d")
    month_str = datetime.now().strftime("%Y-%m")
    csv_path = RESULTS_DIR / month_str / f"{date_str}.csv"

    if not csv_path.exists():
        # Try yesterday
        from datetime import timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        csv_path = RESULTS_DIR / month_str / f"{yesterday}.csv"

    if not csv_path.exists():
        print("No screener CSV found")
        return []

    df = pd.read_csv(csv_path)
    # Get top 10 by daily gain
    top = df.sort_values("Day%", ascending=False).head(10)
    return top["Ticker"].tolist()


def get_trading_agents_graph():
    """Initialize TradingAgents with all features enabled."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "bedrock"
    config["deep_think_llm"] = "claude-sonnet-4-6"
    config["quick_think_llm"] = "claude-haiku-4-5"
    config["max_debate_rounds"] = 2
    config["max_risk_discuss_rounds"] = 2
    config["checkpoint_enabled"] = True
    config["news_article_limit"] = 30
    config["global_news_article_limit"] = 15
    config["global_news_lookback_days"] = 3

    ta = TradingAgentsGraph(
        selected_analysts=["market", "social", "news", "fundamentals"],
        debug=False,
        config=config
    )
    return ta


def run_trading_agents(ticker, date_str):
    """Run TradingAgents full debate on a single ticker."""
    ta = get_trading_agents_graph()

    try:
        _, decision = ta.propagate(ticker, date_str)
        return decision
    except Exception as e:
        print(f"  Error on {ticker}: {e}")
        return None


def run_weekly_reflection(portfolio):
    """Feed past week's P&L back into TradingAgents memory for learning."""
    ta = get_trading_agents_graph()

    # Calculate returns for closed positions
    history_dir = DATA_DIR / "trade_history"
    if not history_dir.exists():
        return

    import glob
    recent_files = sorted(history_dir.glob("*.json"), reverse=True)[:5]
    total_return = 0
    for f in recent_files:
        with open(f) as fh:
            trades = json.load(fh)
            for t in trades:
                if t.get("pnl"):
                    total_return += t["pnl"]

    if total_return != 0:
        try:
            ta.reflect_and_remember(total_return)
            print(f"  Reflection complete. Portfolio return fed: ${total_return:+.2f}")
        except Exception as e:
            print(f"  Reflection error: {e}")


def main():
    import yfinance as yf

    print(f"=== TradingAgents Experiment — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    portfolio = load_portfolio()
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Friday reflection — learn from the week's trades
    if datetime.now().weekday() == 4:  # Friday
        print("Friday — running weekly reflection...")
        run_weekly_reflection(portfolio)
        print()

    # Check exits on existing positions (stop loss at -10%, target at +15%)
    positions_to_sell = []
    for ticker, pos in portfolio["positions"].items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d")
            if hist.empty:
                continue
            price = float(hist["Close"].iloc[-1])
            pnl_pct = (price - pos["entry_price"]) / pos["entry_price"] * 100
            if pnl_pct <= -10:
                positions_to_sell.append((ticker, price, "STOP LOSS (-10%)"))
            elif pnl_pct >= 15:
                positions_to_sell.append((ticker, price, "TARGET HIT (+15%)"))
        except Exception:
            continue

    for ticker, price, reason in positions_to_sell:
        pos = portfolio["positions"][ticker]
        proceeds = pos["shares"] * price
        pnl = proceeds - pos["cost"]
        portfolio["cash"] += proceeds
        print(f"  SELL {ticker} @ ${price:.2f} ({reason}) P&L: ${pnl:+.2f}")

        # Log trade
        trade_history_dir = DATA_DIR / "trade_history"
        trade_history_dir.mkdir(parents=True, exist_ok=True)
        history_file = trade_history_dir / f"{date_str}.json"
        trades = []
        if history_file.exists():
            with open(history_file) as f:
                trades = json.load(f)
        trades.append({
            "action": "SELL", "ticker": ticker, "price": round(price, 2),
            "reason": reason, "pnl": round(pnl, 2), "date": date_str
        })
        with open(history_file, "w") as f:
            json.dump(trades, f, indent=2)

    for ticker, _, _ in positions_to_sell:
        del portfolio["positions"][ticker]

    # Get tickers to analyze
    tickers = get_todays_tickers()
    if not tickers:
        print("No tickers to analyze.")
        save_portfolio(portfolio)
        return

    print(f"Analyzing {len(tickers)} tickers: {', '.join(tickers)}\n")

    decisions = []
    for ticker in tickers[:5]:
        if ticker in portfolio["positions"]:
            continue
        print(f"Running full debate on {ticker}...")
        decision = run_trading_agents(ticker, date_str)
        if decision:
            decisions.append({"ticker": ticker, "decision": str(decision), "date": date_str})
            print(f"  Decision: {str(decision)[:100]}\n")

    # Save full decisions report (for blog)
    decisions_path = DATA_DIR / "decisions" / f"{date_str}.json"
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    with open(decisions_path, "w") as f:
        json.dump(decisions, f, indent=2)

    # Generate daily report (for blog)
    report = generate_daily_report(decisions, portfolio, date_str)
    report_path = DATA_DIR / "reports" / f"{date_str}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report)

    # Apply BUY decisions to portfolio
    buy_decisions = [d for d in decisions if "buy" in d.get("decision", "").lower()]
    if buy_decisions and portfolio["cash"] > 100:
        allocation = portfolio["cash"] / max(len(buy_decisions), 1)
        allocation = min(allocation, portfolio["cash"] * 0.20)

        for d in buy_decisions:
            ticker = d["ticker"]
            if ticker in portfolio["positions"]:
                continue
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period="1d")
                if hist.empty:
                    continue
                price = float(hist["Close"].iloc[-1])
                shares = allocation / price
                cost = shares * price

                portfolio["positions"][ticker] = {
                    "shares": round(shares, 4),
                    "entry_price": round(price, 2),
                    "entry_date": date_str,
                    "cost": round(cost, 2),
                    "decision": d["decision"][:300],
                }
                portfolio["cash"] -= cost
                print(f"  BUY {ticker}: {shares:.2f} shares @ ${price:.2f}")

                # Log trade
                trade_history_dir = DATA_DIR / "trade_history"
                trade_history_dir.mkdir(parents=True, exist_ok=True)
                history_file = trade_history_dir / f"{date_str}.json"
                trades = []
                if history_file.exists():
                    with open(history_file) as fh:
                        trades = json.load(fh)
                trades.append({
                    "action": "BUY", "ticker": ticker, "price": round(price, 2),
                    "decision": d["decision"][:200], "date": date_str
                })
                with open(history_file, "w") as fh:
                    json.dump(trades, fh, indent=2)
            except Exception:
                continue

    save_portfolio(portfolio)

    # Print summary
    total_value = portfolio["cash"]
    for ticker, pos in portfolio["positions"].items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                total_value += pos["shares"] * price
        except Exception:
            total_value += pos["cost"]

    total_return = (total_value - STARTING_CAPITAL) / STARTING_CAPITAL * 100
    portfolio["latest_value"] = round(total_value, 2)
    portfolio["latest_return_pct"] = round(total_return, 2)
    save_portfolio(portfolio)

    print(f"\n{'='*50}")
    print(f"  TradingAgents Portfolio: ${total_value:,.2f} ({total_return:+.2f}%)")
    print(f"  Cash: ${portfolio['cash']:,.2f}")
    print(f"  Positions: {len(portfolio['positions'])}")
    print(f"{'='*50}")


def generate_daily_report(decisions, portfolio, date_str):
    """Generate a markdown report for the blog."""
    report = f"# AI Agent Picks — {date_str}\n\n"
    report += "## Today's Decisions\n\n"
    report += "*Multi-agent debate: Market + Fundamentals + Social + News analysts deliberate, Risk Manager validates.*\n\n"

    buys = [d for d in decisions if "buy" in d.get("decision", "").lower()]
    sells = [d for d in decisions if "sell" in d.get("decision", "").lower()]
    holds = [d for d in decisions if d not in buys and d not in sells]

    if buys:
        report += "### BUY Signals\n\n"
        for d in buys:
            report += f"**{d['ticker']}** — {d['decision'][:300]}\n\n"

    if sells:
        report += "### SELL/AVOID Signals\n\n"
        for d in sells:
            report += f"**{d['ticker']}** — {d['decision'][:300]}\n\n"

    if holds:
        report += "### HOLD/NEUTRAL\n\n"
        for d in holds:
            report += f"**{d['ticker']}** — {d['decision'][:300]}\n\n"

    # Portfolio status
    report += "## Portfolio Status\n\n"
    report += f"- Cash: ${portfolio['cash']:,.2f}\n"
    report += f"- Positions: {len(portfolio['positions'])}\n"
    for ticker, pos in portfolio["positions"].items():
        report += f"- {ticker}: {pos['shares']:.2f} shares @ ${pos['entry_price']:.2f} (since {pos['entry_date']})\n"
    report += "\n"

    return report


if __name__ == "__main__":
    main()

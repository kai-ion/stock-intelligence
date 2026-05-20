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


def run_trading_agents(ticker, date_str):
    """Run TradingAgents debate on a single ticker."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "bedrock"
    config["deep_think_llm"] = "claude-sonnet-4-6"
    config["quick_think_llm"] = "claude-haiku-4-5"
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1

    ta = TradingAgentsGraph(
        selected_analysts=["market", "fundamentals", "news"],
        debug=False,
        config=config
    )

    try:
        _, decision = ta.propagate(ticker, date_str)
        return decision
    except Exception as e:
        print(f"  Error on {ticker}: {e}")
        return None


def main():
    print(f"=== TradingAgents Experiment — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    portfolio = load_portfolio()
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Get tickers to analyze
    tickers = get_todays_tickers()
    if not tickers:
        print("No tickers to analyze.")
        return

    print(f"Analyzing {len(tickers)} tickers: {', '.join(tickers)}\n")

    decisions = []
    for ticker in tickers[:5]:  # Limit to top 5 to manage API costs
        print(f"Running debate on {ticker}...")
        decision = run_trading_agents(ticker, date_str)
        if decision:
            decisions.append({"ticker": ticker, "decision": decision})
            print(f"  Decision: {decision}\n")

    # Save decisions
    decisions_path = DATA_DIR / "decisions" / f"{date_str}.json"
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    with open(decisions_path, "w") as f:
        json.dump(decisions, f, indent=2)

    # Apply BUY decisions to portfolio
    buy_decisions = [d for d in decisions if "buy" in str(d.get("decision", "")).lower()]
    if buy_decisions and portfolio["cash"] > 100:
        allocation = portfolio["cash"] / max(len(buy_decisions), 1)
        allocation = min(allocation, portfolio["cash"] * 0.25)

        for d in buy_decisions:
            ticker = d["ticker"]
            if ticker in portfolio["positions"]:
                continue
            import yfinance as yf
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
                "decision": str(d["decision"])[:200],
            }
            portfolio["cash"] -= cost
            print(f"  BUY {ticker}: {shares:.2f} shares @ ${price:.2f}")

    save_portfolio(portfolio)

    # Print summary
    total_value = portfolio["cash"]
    for ticker, pos in portfolio["positions"].items():
        import yfinance as yf
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1d")
        if not hist.empty:
            price = float(hist["Close"].iloc[-1])
            total_value += pos["shares"] * price

    total_return = (total_value - STARTING_CAPITAL) / STARTING_CAPITAL * 100
    print(f"\n{'='*50}")
    print(f"  TradingAgents Portfolio: ${total_value:,.2f} ({total_return:+.2f}%)")
    print(f"  Cash: ${portfolio['cash']:,.2f}")
    print(f"  Positions: {len(portfolio['positions'])}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()

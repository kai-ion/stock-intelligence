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
RESULTS_DIR = Path(__file__).parent.parent / "screener_output"
_EC2_RESULTS = Path("/home/ec2-user/repo/screener_output")
if _EC2_RESULTS.exists():
    RESULTS_DIR = _EC2_RESULTS
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
    """Get tickers to analyze: mix of momentum, value, and upcoming catalysts."""
    import pandas as pd
    import re as re_mod
    from datetime import timedelta
    date_str = datetime.now().strftime("%Y-%m-%d")
    month_str = datetime.now().strftime("%Y-%m")

    tickers = []

    # 1. Screener stocks with strong momentum BUT not yet extended (Day% between 2-8%)
    csv_path = RESULTS_DIR / month_str / f"{date_str}.csv"
    if not csv_path.exists():
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        csv_path = RESULTS_DIR / month_str / f"{yesterday}.csv"

    if csv_path.exists():
        df = pd.read_csv(csv_path)
        # Sweet spot: positive day but not parabolic, high momentum score
        sweet_spot = df[(df["Day%"] >= 2) & (df["Day%"] <= 10) & (df["Momentum"] >= 60)]
        if not sweet_spot.empty:
            best = sweet_spot.sort_values("Momentum", ascending=False).head(3)["Ticker"].tolist()
            tickers.extend(best)
            print(f"  Momentum sweet spot (2-10% day, high score): {', '.join(best)}")
        else:
            top = df.sort_values("Momentum", ascending=False).head(3)["Ticker"].tolist()
            tickers.extend(top)
            print(f"  Top momentum: {', '.join(top)}")

    # 2. Claude's top picks
    brief_path = RESULTS_DIR / month_str / f"{date_str}_brief.md"
    if not brief_path.exists():
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        brief_path = RESULTS_DIR / month_str / f"{yesterday}_brief.md"

    if brief_path.exists():
        content = brief_path.read_text()
        picks_section = re_mod.search(r"## Claude's Top Picks(.*?)## Avoid", content, re_mod.DOTALL)
        if picks_section:
            pick_tickers = re_mod.findall(r'\*\*([A-Z]{1,5})\*\*', picks_section.group(1))
            claude_picks = [t for t in pick_tickers[:3] if t not in tickers]
            tickers.extend(claude_picks)
            print(f"  Claude's picks: {', '.join(claude_picks)}")

    # 3. Upcoming earnings (from weekly report) — buy BEFORE the move
    monday = datetime.now() - timedelta(days=datetime.now().weekday())
    week_file = Path(f"/home/ec2-user/events/data/week_{monday.strftime('%Y-%m-%d')}.md")
    if week_file.exists():
        week_content = week_file.read_text()
        # Find tickers with BUY action from the weekly report
        buy_tickers = re_mod.findall(r'\*\*([A-Z]{1,5})\*\*.*?Action:\s*BUY', week_content)
        earnings_buys = [t for t in buy_tickers[:2] if t not in tickers]
        if earnings_buys:
            tickers.extend(earnings_buys)
            print(f"  Weekly report BUY-rated earnings: {', '.join(earnings_buys)}")

    # Deduplicate
    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        print("No tickers found")
    return tickers


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
    """Run TradingAgents full debate on a single ticker. Returns (decision, full_state)."""
    ta = get_trading_agents_graph()

    try:
        state, decision = ta.propagate(ticker, date_str)

        # Extract reasoning from state if available
        reasoning = ""
        if isinstance(state, dict):
            # Look for analyst reports, debate transcripts, risk discussion
            for key in ["market_report", "fundamentals_report", "news_report",
                        "social_report", "bull_case", "bear_case",
                        "risk_debate", "final_trade_decision"]:
                if key in state and state[key]:
                    content = str(state[key])
                    if len(content) > 50:
                        reasoning += f"\n**{key.replace('_', ' ').title()}:**\n{content[:500]}\n"

        return {"decision": str(decision), "reasoning": reasoning}
    except Exception as e:
        print(f"  Error on {ticker}: {e}")
        return None


def run_weekly_reflection(portfolio):
    """Friday: review the week's decisions and learn from outcomes."""
    ta = get_trading_agents_graph()

    # Calculate returns for closed positions
    history_dir = DATA_DIR / "trade_history"
    total_return = 0
    if history_dir.exists():
        recent_files = sorted(history_dir.glob("*.json"), reverse=True)[:5]
        for f in recent_files:
            with open(f) as fh:
                trades = json.load(fh)
                for t in trades:
                    if t.get("pnl"):
                        total_return += t["pnl"]

    # Also calculate unrealized P&L on open positions
    import yfinance as yf
    for ticker, pos in portfolio.get("positions", {}).items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                unrealized = (price - pos["entry_price"]) * pos["shares"]
                total_return += unrealized
        except Exception:
            continue

    # Review this week's decisions (what we bought, held, avoided)
    decisions_dir = DATA_DIR / "decisions"
    week_decisions = []
    if decisions_dir.exists():
        from datetime import timedelta
        today = datetime.now()
        for d in range(5):
            day = today - timedelta(days=d)
            day_file = decisions_dir / f"{day.strftime('%Y-%m-%d')}.json"
            if day_file.exists():
                with open(day_file) as f:
                    week_decisions.extend(json.load(f))

    print(f"  Week summary: {len(week_decisions)} decisions made")
    print(f"  Total return (realized + unrealized): ${total_return:+.2f}")

    # Feed to reflection system
    try:
        ta.reflect_and_remember(total_return)
        print(f"  Reflection complete. Memory updated.")
    except Exception as e:
        print(f"  Reflection error: {e}")

    # Save weekly review
    review = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_return": round(total_return, 2),
        "decisions_count": len(week_decisions),
        "decisions_summary": [
            {"ticker": d.get("ticker"), "decision": d.get("decision", "")[:50]}
            for d in week_decisions
        ],
        "portfolio_value": portfolio.get("latest_value", STARTING_CAPITAL),
    }
    review_dir = DATA_DIR / "weekly_reviews"
    review_dir.mkdir(parents=True, exist_ok=True)
    with open(review_dir / f"{datetime.now().strftime('%Y-%m-%d')}.json", "w") as f:
        json.dump(review, f, indent=2)
    print(f"  Weekly review saved")


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
    for ticker in tickers:
        if ticker in portfolio["positions"]:
            continue
        print(f"Running full debate on {ticker}...")
        result = run_trading_agents(ticker, date_str)
        if result:
            decision_text = result["decision"]
            reasoning = result.get("reasoning", "")
            decisions.append({
                "ticker": ticker,
                "decision": decision_text,
                "reasoning": reasoning[:1000],
                "date": date_str
            })
            print(f"  Decision: {decision_text}")
            if reasoning:
                print(f"  Reasoning: {reasoning[:200]}")
            print()

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

    # Apply BUY decisions to portfolio (Overweight = Buy)
    buy_decisions = [d for d in decisions if any(w in d.get("decision", "").lower() for w in ["buy", "overweight"])]
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

    # Save daily snapshot (for equity chart)
    snapshots_dir = DATA_DIR / "snapshots"
    month_dir = snapshots_dir / datetime.now().strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "date": date_str,
        "total_value": round(total_value, 2),
        "cash": round(portfolio["cash"], 2),
        "positions_count": len(portfolio["positions"]),
        "positions": {
            ticker: round(pos["shares"] * total_value / max(total_value, 1) if total_value else pos["cost"], 2)
            for ticker, pos in portfolio["positions"].items()
        },
    }
    # Get actual position values
    for ticker, pos in portfolio["positions"].items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d")
            if not hist.empty:
                snapshot["positions"][ticker] = round(pos["shares"] * float(hist["Close"].iloc[-1]), 2)
        except Exception:
            snapshot["positions"][ticker] = round(pos["cost"], 2)
    with open(month_dir / f"{date_str}.json", "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"\n{'='*50}")
    print(f"  TradingAgents Portfolio: ${total_value:,.2f} ({total_return:+.2f}%)")
    print(f"  Cash: ${portfolio['cash']:,.2f}")
    print(f"  Positions: {len(portfolio['positions'])}")
    print(f"{'='*50}")


def generate_daily_report(decisions, portfolio, date_str):
    """Generate a markdown report for the blog."""
    report = f"# AI Agent Picks — {date_str}\n\n"
    report += "## Today's Decisions\n\n"
    report += "*Multi-agent debate: Market + Fundamentals + Social + News analysts deliberate (2 rounds), Risk Manager validates.*\n\n"

    buys = [d for d in decisions if any(w in d.get("decision", "").lower() for w in ["buy", "overweight"])]
    sells = [d for d in decisions if any(w in d.get("decision", "").lower() for w in ["sell", "underweight"])]
    holds = [d for d in decisions if d not in buys and d not in sells]

    if buys:
        report += "### BUY Signals\n\n"
        for d in buys:
            report += f"**{d['ticker']}** — {d['decision']}\n"
            if d.get("reasoning"):
                report += f"\n{d['reasoning'][:500]}\n"
            report += "\n"

    if sells:
        report += "### SELL/AVOID Signals\n\n"
        for d in sells:
            report += f"**{d['ticker']}** — {d['decision']}\n"
            if d.get("reasoning"):
                report += f"\n{d['reasoning'][:500]}\n"
            report += "\n"

    if holds:
        report += "### HOLD/NEUTRAL\n\n"
        for d in holds:
            report += f"**{d['ticker']}** — {d['decision']}\n"
            if d.get("reasoning"):
                report += f"\n{d['reasoning'][:500]}\n"
            report += "\n"

    if not decisions:
        report += "*No tickers analyzed today.*\n\n"

    # Portfolio status
    report += "## Portfolio Status\n\n"
    report += f"- **Cash:** ${portfolio['cash']:,.2f}\n"
    report += f"- **Positions:** {len(portfolio['positions'])}\n"
    if portfolio["positions"]:
        report += "\n| Ticker | Shares | Entry | Date |\n|--------|--------|-------|------|\n"
        for ticker, pos in portfolio["positions"].items():
            report += f"| {ticker} | {pos['shares']:.2f} | ${pos['entry_price']:.2f} | {pos['entry_date']} |\n"
    else:
        report += "- *No positions — waiting for high-conviction BUY signals*\n"
    report += "\n"

    return report


if __name__ == "__main__":
    main()

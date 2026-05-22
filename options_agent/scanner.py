#!/usr/bin/env python3
"""
Options Agent — Poor Man's Covered Call Scanner

Quarterly: Selects the best mega-cap tech for a LEAP + covered call strategy
Daily: Monitors existing position and recommends short call management (roll, close, hold)

Strategy:
- Budget: $2K for LEAP (or $40K for 100 shares)
- LEAP: Deep ITM, 0.70-0.80 delta, 12-18 month expiry
- Short call: Weekly, 0.15-0.20 delta (safe, less premium)
- One position at a time
- Weeklies for more active management
"""

import robin_stocks.robinhood as r
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent.parent / "portfolio_analysis" / ".env")

DATA_DIR = Path(__file__).parent / "data"
POSITION_FILE = DATA_DIR / "position.json"

WATCHLIST = [
    # Magnificent 7
    "AAPL", "AMZN", "NVDA", "GOOGL", "MSFT", "META", "TSLA",
    # Semiconductors
    "AVGO", "AMD", "INTC", "QCOM", "TXN", "AMAT", "MU", "MRVL", "KLAC",
    # Enterprise Software / Cloud
    "ORCL", "CRM", "ADBE", "NOW", "SHOP", "SNOW", "DDOG", "PANW",
    # Networking / Infra
    "CSCO", "DELL", "IBM", "NET",
    # Consumer Tech / Internet
    "NFLX", "UBER", "ABNB", "COIN",
    # AI / Growth
    "PLTR", "CRWD", "ZS", "RKLB",
]
SHARES_BUDGET = 40000  # Budget for 100 shares
SHORT_CALL_DELTA_TARGET = 0.15  # Conservative — safe, less premium


def login():
    """Log into Robinhood."""
    email = os.environ.get("RH_EMAIL", "")
    password = os.environ.get("RH_PASSWORD", "")
    if not email or not password:
        print("ERROR: RH credentials not set")
        sys.exit(1)

    result = r.login(
        username=email,
        password=password,
        store_session=True,
        pickle_name="rh_session.pickle",
        pickle_path=str(Path(__file__).parent.parent / "portfolio_analysis"),
    )
    if result:
        print("Logged in")
    else:
        print("Login failed")
        sys.exit(1)


def get_options_chain(ticker, expiry_date, option_type="call"):
    """Get options chain for a ticker at a specific expiry."""
    try:
        options = r.options.find_options_by_expiration(
            ticker, expiry_date, optionType=option_type
        )
        return options
    except Exception as e:
        print(f"  Error fetching {ticker} {expiry_date}: {e}")
        return []


def get_available_expirations(ticker):
    """Get all available expiration dates for a ticker."""
    try:
        chains = r.options.get_chains(ticker)
        if chains:
            expirations = chains.get("expiration_dates", [])
            return expirations
        return []
    except Exception:
        return []


def score_leap_candidate(ticker):
    """Score a ticker for covered call suitability.

    Criteria (100 points total):
    1. Trend (25 pts): above 50d and 200d MA
    2. Volatility (20 pts): lower daily moves = safer
    3. Support proximity (20 pts): near 50d MA = good entry, at ATH = bad
    4. Valuation (15 pts): PEG ratio
    5. IV richness (20 pts): higher vol = richer premiums to sell
    """
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")
        info = stock.info

        if hist.empty or len(hist) < 50:
            return None

        close = hist["Close"]
        current_price = float(close.iloc[-1])
        sma_50 = float(close.iloc[-50:].mean())
        sma_200 = float(close.mean())
        high_52w = float(close.max())

        # 1. TREND (0-25): above both MAs
        above_50 = current_price > sma_50
        above_200 = current_price > sma_200
        trend_score = (above_50 * 15) + (above_200 * 10)

        # 2. VOLATILITY (0-20): lower = safer for CC
        daily_returns = close.pct_change().dropna()
        avg_daily_move = float(daily_returns.abs().mean()) * 100
        vol_score = max(0, min(20, 20 - avg_daily_move * 10))

        # 3. SUPPORT PROXIMITY (0-20): near 50d MA = great, far above = risky
        pct_above_50ma = (current_price - sma_50) / sma_50 * 100 if sma_50 > 0 else 0
        pct_from_ath = (high_52w - current_price) / high_52w * 100

        if pct_above_50ma <= 3:
            support_score = 20
        elif pct_above_50ma <= 8:
            support_score = 15
        elif pct_above_50ma <= 15:
            support_score = 10
        elif pct_above_50ma <= 25:
            support_score = 5
        else:
            support_score = 0

        if pct_from_ath >= 5:
            support_score = min(20, support_score + 5)

        # 4. VALUATION (0-15): PEG ratio
        forward_pe = info.get("forwardPE")
        earnings_growth = info.get("earningsGrowth", 0)
        revenue_growth = info.get("revenueGrowth", 0)
        growth_rate = max(earnings_growth or 0, revenue_growth or 0) * 100

        if forward_pe and growth_rate > 0:
            peg = forward_pe / growth_rate
            if peg <= 1.0:
                valuation_score = 15
            elif peg <= 1.5:
                valuation_score = 12
            elif peg <= 2.5:
                valuation_score = 8
            elif peg <= 4.0:
                valuation_score = 4
            else:
                valuation_score = 0
        elif forward_pe and forward_pe < 25:
            valuation_score = 10
        elif forward_pe and forward_pe < 40:
            valuation_score = 5
        else:
            valuation_score = 0

        # 5. IV RICHNESS (0-20): higher vol = fatter premiums to sell
        hist_vol_30d = float(daily_returns.iloc[-30:].std()) * (252 ** 0.5) * 100
        if hist_vol_30d >= 35:
            iv_score = 20
        elif hist_vol_30d >= 28:
            iv_score = 16
        elif hist_vol_30d >= 22:
            iv_score = 12
        elif hist_vol_30d >= 16:
            iv_score = 8
        else:
            iv_score = 4

        # 6. EARNINGS PROXIMITY PENALTY (0 to -30): massive penalty if earnings within 14 days
        earnings_penalty = 0
        earnings_note = ""
        try:
            cal = stock.calendar
            if cal and "Earnings Date" in cal:
                from datetime import date
                earnings_dates = cal["Earnings Date"]
                if not isinstance(earnings_dates, list):
                    earnings_dates = [earnings_dates]
                today = date.today()
                for ed in earnings_dates:
                    days_to_earnings = (ed - today).days
                    if 0 <= days_to_earnings <= 3:
                        earnings_penalty = -30  # Imminent — DO NOT ENTER
                        earnings_note = f"⚠️ EARNINGS IN {days_to_earnings} DAYS"
                    elif 4 <= days_to_earnings <= 7:
                        earnings_penalty = -20  # Very risky
                        earnings_note = f"⚠️ Earnings in {days_to_earnings} days"
                    elif 8 <= days_to_earnings <= 14:
                        earnings_penalty = -10  # Caution
                        earnings_note = f"Earnings in {days_to_earnings} days"
                    elif days_to_earnings > 14:
                        earnings_penalty = 0  # Safe
                        earnings_note = f"Earnings in {days_to_earnings} days (safe)"
                    break
        except Exception:
            pass

        # Affordability
        shares_cost = current_price * 100
        affordable = shares_cost <= SHARES_BUDGET

        total_score = trend_score + vol_score + support_score + valuation_score + iv_score + earnings_penalty

        return {
            "ticker": ticker,
            "price": round(current_price, 2),
            "sma_50": round(sma_50, 2),
            "sma_200": round(sma_200, 2),
            "above_50_ma": above_50,
            "above_200_ma": above_200,
            "pct_above_50ma": round(pct_above_50ma, 1),
            "pct_from_ath": round(pct_from_ath, 1),
            "avg_daily_move_pct": round(avg_daily_move, 3),
            "forward_pe": round(forward_pe, 1) if forward_pe else None,
            "peg": round(peg, 2) if forward_pe and growth_rate > 0 else None,
            "hist_vol_30d": round(hist_vol_30d, 1),
            "trend_score": round(trend_score, 1),
            "vol_score": round(vol_score, 1),
            "support_score": round(support_score, 1),
            "valuation_score": round(valuation_score, 1),
            "iv_score": round(iv_score, 1),
            "earnings_penalty": earnings_penalty,
            "earnings_note": earnings_note,
            "total_score": round(total_score, 1),
            "leap_affordable": affordable,
            "approx_leap_cost": round(shares_cost, 0),
        }
    except Exception as e:
        print(f"  Error scoring {ticker}: {e}")
        return None


def find_best_leap(ticker):
    """Find the best LEAP option for a ticker (deep ITM, 12-18mo expiry)."""
    expirations = get_available_expirations(ticker)
    if not expirations:
        return None

    # Find expiration 12-18 months out
    today = datetime.now().date()
    target_min = today + timedelta(days=365)
    target_max = today + timedelta(days=548)

    leap_expiries = [e for e in expirations if target_min <= datetime.strptime(e, "%Y-%m-%d").date() <= target_max]

    if not leap_expiries:
        # Fallback: longest available
        leap_expiries = sorted(expirations, reverse=True)[:3]

    best_leap = None
    for expiry in leap_expiries[:3]:
        options = get_options_chain(ticker, expiry, "call")
        if not options:
            continue

        for opt in options:
            try:
                delta = float(opt.get("delta") or 0)
                ask = float(opt.get("ask_price") or 0)
                bid = float(opt.get("bid_price") or 0)
                strike = float(opt.get("strike_price") or 0)
                mid_price = (ask + bid) / 2
                cost = mid_price * 100  # Per contract

                # Want highest delta affordable within budget
                # Ideal: 0.70-0.80 delta, but accept 0.50+ if budget constrained
                if 0.45 <= delta <= 0.90 and cost <= LEAP_BUDGET and bid > 0:
                    # Prefer higher delta (closer to ideal 0.75)
                    if best_leap is None or (delta > float(best_leap.get("delta", 0)) and cost <= LEAP_BUDGET):
                        best_leap = {
                            "ticker": ticker,
                            "expiry": expiry,
                            "strike": strike,
                            "delta": delta,
                            "bid": bid,
                            "ask": ask,
                            "mid_price": round(mid_price, 2),
                            "cost": round(cost, 2),
                            "note": "IDEAL" if 0.65 <= delta <= 0.85 else "BUDGET CONSTRAINED (lower delta)",
                        }
            except (TypeError, ValueError):
                continue

    return best_leap


def find_best_short_call(ticker, leap_strike=None):
    """Find the best weekly short call to sell (0.15-0.20 delta)."""
    expirations = get_available_expirations(ticker)
    if not expirations:
        return None

    today = datetime.now().date()
    # Weekly: 5-10 days out
    target_min = today + timedelta(days=4)
    target_max = today + timedelta(days=12)

    weekly_expiries = [e for e in expirations if target_min <= datetime.strptime(e, "%Y-%m-%d").date() <= target_max]

    if not weekly_expiries:
        # Fallback: nearest expiry > 3 days out
        future = [e for e in expirations if datetime.strptime(e, "%Y-%m-%d").date() > today + timedelta(days=3)]
        weekly_expiries = future[:2]

    best_short = None
    for expiry in weekly_expiries:
        options = get_options_chain(ticker, expiry, "call")
        if not options:
            continue

        for opt in options:
            try:
                delta = float(opt.get("delta") or 0)
                bid = float(opt.get("bid_price") or 0)
                strike = float(opt.get("strike_price") or 0)

                # Want 0.12-0.20 delta (safe), decent premium
                if 0.10 <= delta <= 0.22 and bid >= 0.10:
                    # Must be above leap strike
                    if leap_strike and strike <= leap_strike:
                        continue

                    days_to_expiry = (datetime.strptime(expiry, "%Y-%m-%d").date() - today).days
                    annualized_yield = (bid / (strike * 0.01)) * (365 / days_to_expiry) * 100 if days_to_expiry > 0 else 0

                    if best_short is None or abs(delta - SHORT_CALL_DELTA_TARGET) < abs(float(best_short.get("delta", 0)) - SHORT_CALL_DELTA_TARGET):
                        best_short = {
                            "ticker": ticker,
                            "expiry": expiry,
                            "strike": strike,
                            "delta": delta,
                            "bid": bid,
                            "ask": float(opt.get("ask_price") or 0),
                            "days_to_expiry": days_to_expiry,
                            "premium_per_contract": round(bid * 100, 2),
                            "annualized_yield_pct": round(annualized_yield, 1),
                            "prob_otm": round((1 - delta) * 100, 1),
                        }
            except (TypeError, ValueError):
                continue

    return best_short


def load_position():
    """Load current LEAP position."""
    if POSITION_FILE.exists():
        with open(POSITION_FILE) as f:
            return json.load(f)
    return None


def save_position(position):
    """Save current position."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(POSITION_FILE, "w") as f:
        json.dump(position, f, indent=2)


def quarterly_scan():
    """Quarterly: Find the best mega-cap to buy 100 shares + sell covered calls."""
    print("=== QUARTERLY COVERED CALL SCAN ===\n")
    print(f"Budget: ${SHARES_BUDGET:,} (100 shares)\n")
    print("Scoring candidates...")

    scores = []
    for ticker in WATCHLIST:
        score = score_leap_candidate(ticker)
        if score:
            scores.append(score)
            cost_100 = score["price"] * 100
            status = f"✓ ${cost_100:,.0f}" if score["leap_affordable"] else f"✗ ${cost_100:,.0f} (over budget)"
            earnings_flag = f" | {score['earnings_note']}" if score.get('earnings_note') else ""
            print(f"  {ticker}: {score['total_score']} pts | T:{score['trend_score']} V:{score['vol_score']} S:{score['support_score']} Val:{score['valuation_score']} IV:{score['iv_score']} E:{score['earnings_penalty']} | {score['pct_above_50ma']:+.1f}% from 50MA | {score['pct_from_ath']:.1f}% off ATH | {status}{earnings_flag}")

    # Rank by total score, filter affordable
    affordable = [s for s in scores if s["leap_affordable"]]
    affordable.sort(key=lambda x: x["total_score"], reverse=True)

    if not affordable:
        print("\nNo affordable candidates within budget.")
        return

    print(f"\n{'='*60}")
    print(f"  RANKINGS (within ${SHARES_BUDGET:,} budget):")
    for i, s in enumerate(affordable, 1):
        print(f"  #{i} {s['ticker']} — ${s['price']} × 100 = ${s['price']*100:,.0f} | Score: {s['total_score']}")
    print(f"{'='*60}\n")

    # Run TradingAgents debate on top 3 candidates
    print("\n--- TradingAgents Second Opinion ---\n")
    top_3 = affordable[:3]
    agent_opinions = {}
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trading_agents_experiment"))
        from run import run_trading_agents
        date_str = datetime.now().strftime("%Y-%m-%d")
        for candidate in top_3:
            ticker = candidate["ticker"]
            print(f"  Debating {ticker}...")
            decision = run_trading_agents(ticker, date_str)
            if decision:
                agent_opinions[ticker] = str(decision)[:300]
                signal = "BUY" if "buy" in str(decision).lower() else "SELL" if "sell" in str(decision).lower() else "HOLD"
                print(f"    → {signal}: {str(decision)[:150]}")
            else:
                agent_opinions[ticker] = "No decision"
                print(f"    → No decision returned")
            print()
    except Exception as e:
        print(f"  TradingAgents unavailable: {e}\n")

    # Pick the best that TradingAgents also agrees with (or fallback to #1)
    best = affordable[0]
    for candidate in top_3:
        ticker = candidate["ticker"]
        opinion = agent_opinions.get(ticker, "")
        if "buy" in opinion.lower():
            best = candidate
            print(f"✓ TradingAgents confirms: {ticker} is a BUY")
            break
    else:
        print(f"  TradingAgents didn't confirm any top 3. Using score-based pick: {best['ticker']}")

    print(f"\nFinal pick: {best['ticker']} at ${best['price']}")
    print(f"  Cost for 100 shares: ${best['price'] * 100:,.0f}")
    print(f"  Trend: {'Strong' if best['above_50_ma'] and best['above_200_ma'] else 'Weak'}")
    print(f"  Avg daily move: {best['avg_daily_move_pct']:.2f}%\n")

    # Find short call to sell
    print(f"Finding best weekly covered call to sell...")
    login()
    short = find_best_short_call(best["ticker"])
    if short:
        weekly_income = short["premium_per_contract"]
        monthly_est = weekly_income * 4
        annual_est = weekly_income * 52
        cost_basis = best["price"] * 100
        annual_yield = (annual_est / cost_basis) * 100

        print(f"\n  SELL: {short['expiry']} ${short['strike']}C")
        print(f"  Delta: {short['delta']:.2f} | Prob OTM: {short['prob_otm']}%")
        print(f"  Premium: ${short['premium_per_contract']:.0f}/week")
        print(f"  Estimated income: ${monthly_est:.0f}/month | ${annual_est:,.0f}/year")
        print(f"  Annualized yield on cost: {annual_yield:.1f}%")
        print(f"  DTE: {short['days_to_expiry']} days")
    else:
        print("  No suitable short call found")

    # Save recommendation
    recommendation = {
        "scan_date": datetime.now().strftime("%Y-%m-%d"),
        "strategy": "TRUE COVERED CALL (100 shares + weekly short calls)",
        "candidate": best,
        "shares_cost": round(best["price"] * 100, 2),
        "short_call": short,
        "projected_weekly_income": short["premium_per_contract"] if short else 0,
        "projected_annual_yield_pct": round(annual_yield, 1) if short else 0,
        "trading_agents_opinions": agent_opinions,
        "top_3_considered": [s["ticker"] for s in top_3],
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / "latest_scan.json", "w") as f:
        json.dump(recommendation, f, indent=2)

    r.logout()
    print(f"\nSaved to {DATA_DIR / 'latest_scan.json'}")
    return recommendation


def daily_check():
    """Daily: Check if short call needs management (roll, close, hold)."""
    position = load_position()
    if not position:
        print("No active position. Run quarterly scan first.")
        return

    ticker = position["ticker"]
    short_call = position.get("short_call", {})
    expiry = short_call.get("expiry", "")
    strike = short_call.get("strike", 0)

    print(f"=== DAILY CHECK: {ticker} ===")
    print(f"  Short call: {expiry} ${strike}C\n")

    today = datetime.now().date()
    if not expiry:
        print("  No short call active. Finding one to sell...")
        login()
        new_short = find_best_short_call(ticker, position.get("leap", {}).get("strike"))
        if new_short:
            print(f"  SELL: {new_short['expiry']} ${new_short['strike']}C | Delta: {new_short['delta']:.2f} | Premium: ${new_short['premium_per_contract']}")
            print(f"  Prob OTM: {new_short['prob_otm']}% | DTE: {new_short['days_to_expiry']}")
        r.logout()
        return

    days_left = (datetime.strptime(expiry, "%Y-%m-%d").date() - today).days

    print(f"  Days to expiry: {days_left}")

    if days_left <= 1:
        print("  ⚡ EXPIRING TOMORROW — let it expire worthless or close for pennies")
        print("  ACTION: Find new short call to sell after expiry")
        login()
        new_short = find_best_short_call(ticker, position.get("leap", {}).get("strike"))
        if new_short:
            print(f"\n  NEXT SELL: {new_short['expiry']} ${new_short['strike']}C")
            print(f"  Delta: {new_short['delta']:.2f} | Premium: ${new_short['premium_per_contract']} | Prob OTM: {new_short['prob_otm']}%")
        r.logout()

    elif days_left <= 3:
        print("  ⚠️  EXPIRING SOON — monitor for roll opportunity")
        print("  ACTION: If >50% profit captured, close and roll to next week")

    else:
        print("  ✓ HOLD — position is fine, check back tomorrow")


def main():
    import sys
    if "--scan" in sys.argv:
        quarterly_scan()
    else:
        daily_check()


if __name__ == "__main__":
    main()

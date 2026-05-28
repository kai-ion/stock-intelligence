#!/usr/bin/env python3
"""
Fetch Robinhood portfolio holdings and save to JSON.
Runs daily at 9:50 AM ET before market open.
"""

import robin_stocks.robinhood as r
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Load credentials
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

RH_EMAIL = os.environ.get("RH_EMAIL", "")
RH_PASSWORD = os.environ.get("RH_PASSWORD", "")
RH_TOTP_SECRET = os.environ.get("RH_TOTP_SECRET", "")


def generate_totp(secret):
    """Generate a TOTP code from secret."""
    import pyotp
    totp = pyotp.TOTP(secret)
    return totp.now()


def login():
    """Log into Robinhood."""
    if not RH_EMAIL or not RH_PASSWORD:
        print("ERROR: RH_EMAIL and RH_PASSWORD must be set in .env")
        sys.exit(1)

    login_kwargs = {
        "username": RH_EMAIL,
        "password": RH_PASSWORD,
        "store_session": True,
        "pickle_name": "rh_session.pickle",
        "pickle_path": str(Path(__file__).parent),
    }

    if RH_TOTP_SECRET:
        login_kwargs["mfa_code"] = generate_totp(RH_TOTP_SECRET)

    result = r.login(**login_kwargs)
    if result:
        print("Logged in successfully")
    else:
        print("ERROR: Login failed")
        sys.exit(1)


def fetch_holdings():
    """Fetch current stock holdings with key metrics."""
    holdings = r.build_holdings(with_dividends=False)
    return holdings


def fetch_portfolio_summary():
    """Fetch overall portfolio stats."""
    profile = r.load_portfolio_profile()
    return {
        "market_value": profile.get("market_value"),
        "equity": profile.get("equity"),
        "equity_previous_close": profile.get("equity_previous_close"),
        "withdrawable": profile.get("withdrawable_amount"),
    }


def main():
    print(f"=== Portfolio Fetch — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    login()

    print("Fetching holdings...")
    holdings = fetch_holdings()

    print("Fetching portfolio summary...")
    summary = fetch_portfolio_summary()

    output = {
        "timestamp": datetime.now().isoformat(),
        "portfolio_summary": summary,
        "holdings": holdings,
    }

    # Save to dated JSON
    output_dir = Path(__file__).parent / "data"
    output_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = output_dir / f"{date_str}.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    # Print summary
    print(f"\nPortfolio Value: ${float(summary.get('equity', 0)):,.2f}")
    prev = float(summary.get("equity_previous_close", 0))
    curr = float(summary.get("equity", 0))
    if prev > 0:
        day_change = (curr - prev) / prev * 100
        print(f"Day Change: {day_change:+.2f}%")

    print(f"\nHoldings ({len(holdings)} positions):")
    print(f"{'Ticker':<8} {'Shares':<10} {'Avg Cost':<10} {'Price':<10} {'P&L %':<10} {'Equity':<12}")
    print("-" * 60)

    sorted_holdings = sorted(holdings.items(), key=lambda x: float(x[1].get("equity", 0)), reverse=True)
    for ticker, data in sorted_holdings:
        shares = float(data.get("quantity", 0))
        avg_cost = float(data.get("average_buy_price", 0))
        price = float(data.get("price", 0))
        pct = float(data.get("percent_change", 0))
        equity = float(data.get("equity", 0))
        print(f"{ticker:<8} {shares:<10.2f} ${avg_cost:<9.2f} ${price:<9.2f} {pct:<+9.2f}% ${equity:<11,.2f}")

    print(f"\nSaved to {output_path}")

    r.logout()


if __name__ == "__main__":
    main()

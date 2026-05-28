#!/usr/bin/env python3
"""
Financial analysis skills adapted from anthropics/financial-services.
Uses yfinance as data source instead of FactSet/CapIQ MCP servers.
Provides earnings deep-dive and comps valuation for the daily pipeline.
"""

import yfinance as yf
import json
from datetime import datetime


def get_peer_group(ticker):
    """Get peer companies in the same sector/industry."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        industry = info.get("industry", "")
        sector = info.get("sector", "")

        # Common peer mappings for popular sectors
        PEER_MAP = {
            "Semiconductors": ["NVDA", "AMD", "INTC", "QCOM", "AVGO", "MU", "MRVL", "TXN", "AMAT", "KLAC"],
            "Software - Infrastructure": ["MSFT", "ORCL", "NOW", "SNOW", "DDOG", "MDB", "NET", "CRWD"],
            "Software - Application": ["CRM", "ADBE", "INTU", "WDAY", "ZS", "PANW", "HUBS"],
            "Internet Content & Information": ["GOOGL", "META", "SNAP", "PINS", "RDDT"],
            "Consumer Electronics": ["AAPL", "SONY", "SAMSUNG"],
            "Biotechnology": ["MRNA", "PFE", "ABBV", "LLY", "AMGN", "GILD", "REGN"],
            "Oil & Gas E&P": ["XOM", "CVX", "COP", "EOG", "PXD", "DVN", "OXY"],
            "Banks - Diversified": ["JPM", "BAC", "WFC", "C", "GS", "MS"],
            "Aerospace & Defense": ["LMT", "RTX", "BA", "NOC", "GD", "RKLB"],
            "Specialty Retail": ["HD", "LOW", "TGT", "COST", "WMT"],
        }

        # Find peers from map or use sector
        peers = PEER_MAP.get(industry, [])
        if not peers:
            for key, val in PEER_MAP.items():
                if key.lower() in industry.lower() or key.lower() in sector.lower():
                    peers = val
                    break

        # Remove the ticker itself and limit to 6 peers
        peers = [p for p in peers if p != ticker][:6]
        return peers
    except Exception:
        return []


def get_comps_data(ticker):
    """Get comparable company valuation multiples."""
    peers = get_peer_group(ticker)
    if not peers:
        return None

    all_tickers = [ticker] + peers
    comps = []

    for t in all_tickers:
        try:
            stock = yf.Ticker(t)
            info = stock.info
            comps.append({
                "ticker": t,
                "name": info.get("shortName", t),
                "market_cap_b": round(info.get("marketCap", 0) / 1e9, 1),
                "pe_forward": info.get("forwardPE"),
                "pe_trailing": info.get("trailingPE"),
                "ev_ebitda": info.get("enterpriseToEbitda"),
                "ev_revenue": info.get("enterpriseToRevenue"),
                "revenue_growth": round(info.get("revenueGrowth", 0) * 100, 1) if info.get("revenueGrowth") else None,
                "profit_margin": round(info.get("profitMargins", 0) * 100, 1) if info.get("profitMargins") else None,
                "roe": round(info.get("returnOnEquity", 0) * 100, 1) if info.get("returnOnEquity") else None,
            })
        except Exception:
            continue

    if len(comps) < 2:
        return None

    # Calculate peer medians (excluding the target)
    peer_data = [c for c in comps if c["ticker"] != ticker]
    target_data = next((c for c in comps if c["ticker"] == ticker), None)

    def median(values):
        values = [v for v in values if v is not None]
        if not values:
            return None
        values.sort()
        n = len(values)
        return values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2

    peer_medians = {
        "pe_forward": median([c["pe_forward"] for c in peer_data]),
        "ev_ebitda": median([c["ev_ebitda"] for c in peer_data]),
        "ev_revenue": median([c["ev_revenue"] for c in peer_data]),
        "revenue_growth": median([c["revenue_growth"] for c in peer_data]),
        "profit_margin": median([c["profit_margin"] for c in peer_data]),
    }

    # Determine if target is cheap/expensive vs peers
    valuation_vs_peers = "FAIR"
    if target_data and peer_medians["pe_forward"]:
        if target_data.get("pe_forward") and peer_medians["pe_forward"]:
            ratio = target_data["pe_forward"] / peer_medians["pe_forward"]
            if ratio < 0.75:
                valuation_vs_peers = "CHEAP"
            elif ratio > 1.3:
                valuation_vs_peers = "EXPENSIVE"

    return {
        "target": target_data,
        "peers": peer_data,
        "peer_medians": peer_medians,
        "valuation_vs_peers": valuation_vs_peers,
    }


def get_earnings_transcript_summary(ticker):
    """Get earnings-related news and data for a ticker that recently reported."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        news = stock.news

        # Extract earnings-related headlines
        earnings_news = []
        for item in news[:10]:
            content = item.get("content", {})
            title = content.get("title", "")
            summary = content.get("summary", "")
            if any(kw in title.lower() for kw in ["earnings", "revenue", "profit", "quarter", "guidance", "beat", "miss", "eps", "outlook"]):
                earnings_news.append({"title": title, "summary": summary})

        # Get financial data
        financials = {
            "revenue_growth": round(info.get("revenueGrowth", 0) * 100, 1) if info.get("revenueGrowth") else None,
            "earnings_growth": round(info.get("earningsGrowth", 0) * 100, 1) if info.get("earningsGrowth") else None,
            "profit_margin": round(info.get("profitMargins", 0) * 100, 1) if info.get("profitMargins") else None,
            "forward_pe": info.get("forwardPE"),
            "trailing_pe": info.get("trailingPE"),
            "analyst_target": info.get("targetMeanPrice"),
            "recommendation": info.get("recommendationKey"),
            "num_analysts": info.get("numberOfAnalystOpinions"),
        }

        return {
            "ticker": ticker,
            "name": info.get("shortName", ticker),
            "earnings_news": earnings_news[:5],
            "financials": financials,
        }
    except Exception:
        return None


if __name__ == "__main__":
    # Test
    print("=== Comps for NVDA ===")
    comps = get_comps_data("NVDA")
    if comps:
        print(f"Valuation vs peers: {comps['valuation_vs_peers']}")
        print(f"Target P/E: {comps['target']['pe_forward']}")
        print(f"Peer median P/E: {comps['peer_medians']['pe_forward']}")
        for p in comps['peers']:
            print(f"  {p['ticker']}: P/E={p['pe_forward']}, EV/EBITDA={p['ev_ebitda']}")

    print("\n=== Earnings for CSCO ===")
    earnings = get_earnings_transcript_summary("CSCO")
    if earnings:
        print(json.dumps(earnings, indent=2))

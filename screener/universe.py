"""
Universe definition.

For the prototype we screen a curated seed of liquid US large-cap growth names
drawn from the Russell 1000. This is enough to validate the detector by eye.

The full live constituent list should be sourced from the iShares Russell 1000
ETF (IWB) holdings CSV, which BlackRock publishes daily and is the standard
free source. `load_iwb_holdings` is the documented hook for that step; it is
not wired into the prototype run yet because it depends on a sometimes-flaky
public endpoint that we do not want as a hard dependency during detector
development.
"""

from __future__ import annotations

import csv
import io

# Curated seed: liquid Russell 1000 names spanning leadership themes
# (semis, software, consumer, industrials, financials, healthcare). Chosen for
# liquidity and chartability, not as a recommendation list.
SEED_UNIVERSE: list[str] = [
    # Mega-cap / semis
    "NVDA", "AVGO", "AMD", "MU", "LRCX", "KLAC", "AMAT", "ASML",
    # Software / platforms
    "MSFT", "CRM", "NOW", "PANW", "CRWD", "SNOW", "DDOG", "NET", "ANET",
    # Consumer / internet
    "AMZN", "META", "GOOGL", "NFLX", "BKNG", "CMG", "LULU", "DKNG",
    # Industrials / energy transition
    "GE", "CAT", "ETN", "PWR", "VRT", "FSLR",
    # Healthcare / med-tech
    "LLY", "ISRG", "VRTX", "REGN", "DXCM",
    # Financials / fintech
    "JPM", "V", "MA", "AXP", "COIN", "HOOD",
    # Other leadership
    "COST", "TSLA", "UBER", "AXON", "CELH",
]


def load_iwb_holdings(csv_text: str) -> list[str]:
    """Parse iShares IWB holdings CSV text into a ticker list.

    The IWB holdings file has a preamble of metadata rows before the header
    row that begins with "Ticker". We skip to that header, then read the
    Ticker column, keeping only equity holdings and dropping cash/derivative
    lines.

    This is intentionally a pure text-parsing function so it can be unit
    tested without a network call. The download itself is left to the caller.
    """
    lines = csv_text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("Ticker"):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Could not locate the 'Ticker' header row in IWB CSV.")

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    tickers: list[str] = []
    for row in reader:
        ticker = (row.get("Ticker") or "").strip()
        asset_class = (row.get("Asset Class") or "").strip().lower()
        if not ticker or ticker == "-":
            continue
        if asset_class and asset_class != "equity":
            continue
        # yfinance uses '-' where some feeds use '.' for share classes.
        tickers.append(ticker.replace(".", "-"))
    return tickers


def get_universe() -> list[str]:
    """Return the ticker universe for a screen run.

    Prototype: the seed list. Swap in `load_iwb_holdings` output once the
    holdings download is wired up and we are ready to run the full Russell
    1000.
    """
    return list(SEED_UNIVERSE)

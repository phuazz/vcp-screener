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
import json
import urllib.request
from pathlib import Path

_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120 Safari/537.36")
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_PROXY_CACHE = _DATA_DIR / "universe_proxy.json"
_IWB_OVERRIDE = _DATA_DIR / "iwb_holdings.csv"

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


def load_sp_proxy(refresh: bool = False) -> list[str]:
    """Russell 1000 proxy: the S&P 500 + S&P 400 constituents (~900 of the
    largest US names), scraped from Wikipedia and cached to disk.

    This is a proxy, not the exact Russell 1000. The iShares IWB holdings file
    is the authoritative source, but its download is bot-walled from automated
    environments; drop an official `data/iwb_holdings.csv` to override this.
    Membership barely affects an indicative, survivorship-biased backtest, so a
    well-defined large-cap proxy is an honest stand-in.
    """
    if not refresh and _PROXY_CACHE.exists():
        try:
            return json.loads(_PROXY_CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass

    import pandas as pd  # local import: only needed when refreshing

    def _wiki(url: str, col: str = "Symbol") -> list[str]:
        req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
        table = next(t for t in pd.read_html(io.StringIO(html)) if col in t.columns)
        return [str(s).strip().upper().replace(".", "-")
                for s in table[col].tolist() if str(s).strip()]

    tickers = sorted(set(
        _wiki("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        + _wiki("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies")
    ))
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _PROXY_CACHE.write_text(json.dumps(tickers), encoding="utf-8")
    return tickers


def get_universe() -> list[str]:
    """Return the ticker universe for a screen or backtest run.

    Resolution order: an official IWB holdings CSV if present, else the cached
    or freshly scraped S&P 500 + 400 proxy, else the curated seed as a last
    resort if both network paths fail.
    """
    if _IWB_OVERRIDE.exists():
        try:
            return load_iwb_holdings(_IWB_OVERRIDE.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        proxy = load_sp_proxy()
        if proxy:
            return proxy
    except Exception:
        pass
    return list(SEED_UNIVERSE)

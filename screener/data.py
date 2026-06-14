"""
Data layer: fetch EOD OHLCV from yfinance with a simple on-disk cache.

Prototype source only. yfinance has no delisted history and unreliable
adjustments, so it must never become the production source — see README.
Production should run on Norgate (survivorship-bias-free, point-in-time
constituents) or a comparable feed.

All prices are auto-adjusted for splits and dividends so that swing
percentages and moving averages are computed on a continuous series.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import yfinance as yf

from config import CONFIG

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker}_{CONFIG.history_period}_{CONFIG.interval}.parquet"


def fetch_one(ticker: str, use_cache: bool = True, max_age_hours: float = 18.0) -> pd.DataFrame:
    """Fetch a single ticker as a tidy OHLCV frame indexed by date.

    Columns: Open, High, Low, Close, Volume. Returns an empty frame on
    failure rather than raising, so a bad ticker does not abort a universe run.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(ticker)

    if use_cache and path.exists():
        age_hours = (time.time() - path.stat().st_mtime) / 3600.0
        if age_hours < max_age_hours:
            try:
                return pd.read_parquet(path)
            except Exception:
                pass  # fall through to a fresh download

    try:
        df = yf.download(
            ticker,
            period=CONFIG.history_period,
            interval=CONFIG.interval,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    # yfinance returns a column MultiIndex (field, ticker) for single names.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.index.name = "Date"

    try:
        df.to_parquet(path)
    except Exception:
        pass  # cache write is best-effort

    return df


def fetch_many(tickers: list[str], **kwargs) -> dict[str, pd.DataFrame]:
    """Fetch a list of tickers serially. Returns ticker -> frame.

    Serial by design for the prototype: kinder to the public endpoint and
    easier to reason about than threaded downloads. Empty frames are dropped.
    """
    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        df = fetch_one(t, **kwargs)
        if not df.empty:
            out[t] = df
    return out

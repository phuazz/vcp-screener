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


def _bulk_cache_path(ticker: str, period: str) -> Path:
    return CACHE_DIR / f"{ticker}_{period}_1d.parquet"


def fetch_bulk(tickers: list[str], period: str, chunk: int = 120,
               use_cache: bool = True, max_age_hours: float = 18.0) -> dict[str, pd.DataFrame]:
    """Fetch many tickers efficiently for a given period. Returns ticker -> frame.

    Cached frames (fresh enough) are read from parquet; the remainder are
    downloaded in threaded chunks via a single yf.download call per chunk, which
    is far faster than serial fetching for a large universe. Bad or empty
    tickers are simply dropped rather than aborting the run.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, pd.DataFrame] = {}
    missing: list[str] = []

    for t in tickers:
        path = _bulk_cache_path(t, period)
        if use_cache and path.exists():
            age = (time.time() - path.stat().st_mtime) / 3600.0
            if age < max_age_hours:
                try:
                    out[t] = pd.read_parquet(path)
                    continue
                except Exception:
                    pass
        missing.append(t)

    for start in range(0, len(missing), chunk):
        batch = missing[start:start + chunk]
        try:
            raw = yf.download(batch, period=period, interval="1d", auto_adjust=True,
                              progress=False, threads=True, group_by="ticker")
        except Exception:
            continue
        if raw is None or raw.empty:
            continue
        for t in batch:
            try:
                sub = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                sub = sub[["Open", "High", "Low", "Close", "Volume"]].dropna()
            except Exception:
                continue
            if sub.empty:
                continue
            sub.index.name = "Date"
            out[t] = sub
            try:
                sub.to_parquet(_bulk_cache_path(t, period))
            except Exception:
                pass

    return out

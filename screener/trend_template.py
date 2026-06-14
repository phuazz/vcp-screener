"""
Minervini Trend Template — the Stage 2 uptrend prefilter — plus the
cross-sectional relative-strength score.

The Trend Template gate is evaluated per name from its own price history. The
RS rank is the one cross-sectional piece: each name gets a raw RS score, and
the percentile rank is assigned across the whole universe in a separate pass
(see rs_rank_universe), because a percentile is only meaningful relative to the
field being screened.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import CONFIG


@dataclass
class TrendResult:
    passed: bool
    reasons: list[str]            # which conditions failed (empty if passed)
    rs_score: float               # raw weighted-return RS score
    close: float
    pct_below_52w_high: float
    pct_above_52w_low: float


def rs_score(df: pd.DataFrame) -> float:
    """IBD-style weighted return: recent quarter double-weighted.

    Returns a raw score (a blended total return). NaN if insufficient history.
    """
    q = CONFIG.rs.quarter_days
    weights = CONFIG.rs.weights
    need = q * len(weights)
    close = df["Close"]
    if len(close) < need + 1:
        return float("nan")

    score = 0.0
    for k, w in enumerate(weights):
        end = -1 - k * q
        start = -1 - (k + 1) * q
        # period return over quarter k (0 = most recent)
        p_end = close.iloc[end]
        p_start = close.iloc[start]
        if p_start <= 0:
            return float("nan")
        score += w * (p_end / p_start - 1.0)
    return float(score)


def evaluate_trend_template(df: pd.DataFrame) -> TrendResult:
    """Evaluate the Trend Template for one name (RS rank applied separately)."""
    cfg = CONFIG.trend
    close = df["Close"]
    reasons: list[str] = []

    need = cfg.sma_long + cfg.sma_long_rising_days
    if len(close) < need:
        return TrendResult(False, ["insufficient_history"], float("nan"),
                           float(close.iloc[-1]) if len(close) else float("nan"),
                           float("nan"), float("nan"))

    price = float(close.iloc[-1])
    sma50 = close.rolling(cfg.sma_short).mean()
    sma150 = close.rolling(cfg.sma_mid).mean()
    sma200 = close.rolling(cfg.sma_long).mean()

    s50 = float(sma50.iloc[-1])
    s150 = float(sma150.iloc[-1])
    s200 = float(sma200.iloc[-1])
    s200_prior = float(sma200.iloc[-1 - cfg.sma_long_rising_days])

    high_52w = float(close.iloc[-252:].max()) if len(close) >= 252 else float(close.max())
    low_52w = float(close.iloc[-252:].min()) if len(close) >= 252 else float(close.min())

    pct_below_high = high_52w / price - 1.0 if price > 0 else float("inf")
    pct_above_low = price / low_52w - 1.0 if low_52w > 0 else float("inf")

    # The eight Trend Template conditions.
    if not price > s150:
        reasons.append("price<=SMA150")
    if not price > s200:
        reasons.append("price<=SMA200")
    if not s150 > s200:
        reasons.append("SMA150<=SMA200")
    if not s200 > s200_prior:
        reasons.append("SMA200_not_rising")
    if not s50 > s150:
        reasons.append("SMA50<=SMA150")
    if not price > s50:
        reasons.append("price<=SMA50")
    if not pct_above_low >= cfg.min_pct_above_52w_low:
        reasons.append("too_close_to_52w_low")
    if not pct_below_high <= cfg.max_pct_below_52w_high:
        reasons.append("too_far_below_52w_high")

    return TrendResult(
        passed=len(reasons) == 0,
        reasons=reasons,
        rs_score=rs_score(df),
        close=price,
        pct_below_52w_high=pct_below_high,
        pct_above_52w_low=pct_above_low,
    )


def rs_rank_universe(scores: dict[str, float]) -> dict[str, float]:
    """Assign a 0-100 percentile RS rank across the universe.

    Names with NaN scores are excluded from ranking and returned as NaN.
    """
    valid = {t: s for t, s in scores.items() if s == s}  # drop NaN
    if not valid:
        return {t: float("nan") for t in scores}
    s = pd.Series(valid)
    ranks = s.rank(pct=True) * 100.0
    out = {t: float("nan") for t in scores}
    for t, r in ranks.items():
        out[t] = float(r)
    return out

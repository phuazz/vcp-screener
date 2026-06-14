"""
VCP analysis: turn the detected swings into a volatility-contraction verdict.

Maps directly onto the four elements:
  1. Contracting swings  -> contraction depth sequence is decreasing.
  2. Signs of accumulation -> pocket pivots / strong-volume up days in the base.
  3. Dry volume on the right -> recent average volume below the base average.
  4. Final contraction -> last leg tight and last N sessions in a narrow range.

The pivot (breakout line) is the most recent confirmed swing high. The stop is
placed just below the most recent confirmed swing low — the floor of the final
contraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from config import CONFIG
from .swings import Swing, detect_swings


@dataclass
class VCPResult:
    is_vcp: bool
    reasons: list[str] = field(default_factory=list)
    contractions: list[float] = field(default_factory=list)  # depths, widest->tightest
    pivot: float = float("nan")          # breakout line (last swing high)
    stop: float = float("nan")           # below last swing low
    final_range_pct: float = float("nan")
    recent_vol_ratio: float = float("nan")
    accumulation_signals: int = 0
    num_contractions: int = 0


def _contraction_depths(swings: list[Swing]) -> list[float]:
    """Peak-to-trough depths for each High->Low leg, in chronological order.

    A contraction is measured from a swing high to the following swing low:
    (high - low) / high. We only count H->L legs (the pullbacks).
    """
    depths: list[float] = []
    for a, b in zip(swings, swings[1:]):
        if a.kind == "H" and b.kind == "L" and a.price > 0:
            depths.append((a.price - b.price) / a.price)
    return depths


def _accumulation_signals(df: pd.DataFrame, start_idx: int) -> int:
    """Count pocket pivots and strong-volume up days from start_idx onward."""
    cfg = CONFIG.volume
    close = df["Close"].to_numpy()
    vol = df["Volume"].to_numpy()
    n = len(df)
    avg50 = pd.Series(vol).rolling(50).mean().to_numpy()

    signals = 0
    for i in range(max(start_idx, cfg.pocket_lookback), n):
        up_day = close[i] > close[i - 1]
        if not up_day:
            continue
        # Pocket pivot: up-day volume tops the highest down-day volume in the
        # trailing window.
        window = range(i - cfg.pocket_lookback, i)
        down_vols = [vol[j] for j in window if close[j] < close[j - 1]]
        is_pocket = bool(down_vols) and vol[i] > max(down_vols)
        # Strong rally: volume well above the 50-day average.
        strong = avg50[i] == avg50[i] and vol[i] > cfg.rally_vol_multiple * avg50[i]
        if is_pocket or strong:
            signals += 1
    return signals


def analyse_vcp(df: pd.DataFrame) -> VCPResult:
    """Run the full VCP test over the trailing base window."""
    vcfg = CONFIG.vcp
    volcfg = CONFIG.volume

    if len(df) < vcfg.base_lookback_days:
        return VCPResult(False, ["insufficient_history"])

    base = df.iloc[-vcfg.base_lookback_days :].copy()
    swings = detect_swings(base, CONFIG.swing.reversal_pct)

    reasons: list[str] = []

    # Isolate the consolidation. The base ceiling is the highest swing high in
    # the window; contractions are only the pullbacks that occur from that high
    # forward. Measuring across the whole window would count the prior uptrend's
    # legs as "contractions", which they are not. For a Trend-Template name
    # (within 25 per cent of its 52-week high) the window high is the relevant
    # base ceiling. This is the documented base-start simplification for v1.
    high_swings = [s for s in swings if s.kind == "H"]
    if high_swings:
        base_high = max(high_swings, key=lambda s: s.price)
        base_swings = [s for s in swings if s.idx >= base_high.idx]
    else:
        base_swings = swings

    depths = _contraction_depths(base_swings)
    num = len(depths)

    if num < vcfg.min_contractions:
        reasons.append(f"too_few_contractions({num})")
    if num > vcfg.max_contractions:
        # Too many legs usually means a loose, choppy base, not a clean VCP.
        reasons.append(f"too_many_contractions({num})")

    # 1. Contractions must tighten left to right (within tolerance).
    if num >= vcfg.min_contractions:
        for prev, cur in zip(depths, depths[1:]):
            if cur > prev * vcfg.contraction_tolerance:
                reasons.append("contractions_not_tightening")
                break
        if depths[0] > vcfg.max_first_contraction:
            reasons.append("first_contraction_too_deep")
        if depths[-1] > vcfg.max_final_contraction:
            reasons.append("final_contraction_too_deep")

    # 4. Final contraction tightness over the last N sessions.
    tail = base.iloc[-vcfg.final_range_days :]
    final_range_pct = float("nan")
    if not tail.empty:
        hi = float(tail["High"].max())
        lo = float(tail["Low"].min())
        if hi > 0:
            final_range_pct = (hi - lo) / hi
            if final_range_pct > vcfg.max_final_range_pct:
                reasons.append("final_range_too_wide")

    # 3. Dry volume on the right.
    recent_vol = float(base["Volume"].iloc[-volcfg.recent_days :].mean())
    base_vol = float(base["Volume"].mean())
    recent_vol_ratio = recent_vol / base_vol if base_vol > 0 else float("inf")
    if recent_vol_ratio > volcfg.max_recent_vol_ratio:
        reasons.append("volume_not_drying")

    # 2. Accumulation signatures inside the base.
    acc = _accumulation_signals(base, start_idx=0)
    if acc < volcfg.min_accumulation_signals:
        reasons.append("no_accumulation_signal")

    # Pivot and stop from the most recent confirmed swings within the base.
    last_high = next((s for s in reversed(base_swings) if s.kind == "H"), None)
    last_low = next((s for s in reversed(base_swings) if s.kind == "L"), None)
    pivot = float(last_high.price) if last_high else float("nan")
    stop = float(last_low.price) if last_low else float("nan")

    return VCPResult(
        is_vcp=len(reasons) == 0,
        reasons=reasons,
        contractions=[round(d, 4) for d in depths],
        pivot=pivot,
        stop=stop,
        final_range_pct=final_range_pct,
        recent_vol_ratio=recent_vol_ratio,
        accumulation_signals=acc,
        num_contractions=num,
    )

"""
Swing (pivot) detection — the load-bearing piece of the whole screen.

We use a ZigZag rule rather than a fixed-window fractal. A new pivot is only
confirmed once price retraces at least `reversal_pct` from the running extreme
in the opposite direction. This produces a clean alternating sequence of swing
highs and lows whose legs are directly comparable as percentage moves — which
is exactly what a VCP measures.

Why ZigZag and not a rolling max/min fractal: a fractal keys off a fixed bar
window and tends to over-fragment quiet bases (every wiggle becomes a pivot) or
miss tightening when the window is large. The percentage-reversal rule scales
naturally with the contraction we are trying to detect.

Known property to keep honest: the final, unconfirmed leg. The most recent move
from the last confirmed pivot may not yet have retraced enough to be its own
pivot. We expose the running extreme separately so callers can reason about the
in-progress leg (it matters for the pivot/breakout line) without pretending it
is a confirmed swing.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Swing:
    """A confirmed swing point."""

    idx: int          # positional index into the frame
    date: pd.Timestamp
    price: float
    kind: str         # "H" for swing high, "L" for swing low


def detect_swings(df: pd.DataFrame, reversal_pct: float) -> list[Swing]:
    """Detect alternating swing highs and lows via the ZigZag rule.

    Uses intraday High for up-extremes and Low for down-extremes so the leg
    depths reflect the true range, not just close-to-close. Returns swings in
    chronological order; consecutive swings always alternate H, L, H, L, ...
    """
    highs = df["High"].to_numpy()
    lows = df["Low"].to_numpy()
    dates = df.index

    n = len(df)
    if n == 0:
        return []

    swings: list[Swing] = []

    # direction: 0 = unknown (seeking the first pivot), +1 = tracking an
    # up-leg toward a swing high, -1 = tracking a down-leg toward a swing low.
    # Exactly one branch runs per bar (if / elif), so a single wide-range bar
    # cannot confirm both a high and a low — that double-count was the bug.
    direction = 0
    hi_idx, hi_price = 0, highs[0]   # running up-extreme and its index
    lo_idx, lo_price = 0, lows[0]    # running down-extreme and its index

    for i in range(1, n):
        if direction >= 0:
            # Tracking the running high; confirm it only on a sufficient drop.
            if highs[i] >= hi_price:
                hi_price, hi_idx = highs[i], i
            elif lows[i] <= hi_price * (1.0 - reversal_pct):
                swings.append(Swing(hi_idx, dates[hi_idx], float(hi_price), "H"))
                direction = -1
                lo_price, lo_idx = lows[i], i
        else:
            # Tracking the running low; confirm it only on a sufficient rally.
            if lows[i] <= lo_price:
                lo_price, lo_idx = lows[i], i
            elif highs[i] >= lo_price * (1.0 + reversal_pct):
                swings.append(Swing(lo_idx, dates[lo_idx], float(lo_price), "L"))
                direction = 1
                hi_price, hi_idx = highs[i], i

    return swings


def running_extreme(df: pd.DataFrame, last_swing: Swing | None) -> tuple[str, float]:
    """Return the in-progress (unconfirmed) leg's extreme after the last swing.

    If the last confirmed swing is a low, the in-progress leg is an up-leg and
    we return ("H", highest high since that low). Vice versa for a high. This
    is what defines the candidate pivot/breakout line on the right edge.
    """
    if last_swing is None:
        return ("H", float(df["High"].max()))

    tail = df.iloc[last_swing.idx + 1 :]
    if tail.empty:
        return (last_swing.kind, last_swing.price)

    if last_swing.kind == "L":
        return ("H", float(tail["High"].max()))
    return ("L", float(tail["Low"].min()))

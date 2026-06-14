"""
VCP screener — orchestrator.

Pipeline per run:
  1. Fetch EOD OHLCV for the universe (yfinance, prototype only).
  2. Liquidity floor.
  3. Trend Template gate (per name) + cross-sectional RS rank.
  4. VCP analysis over the surviving names.
  5. Emit a candidate list (JSON + console table) with pivot and stop.

Run:  python run_screen.py [--no-cache] [--all]
  --no-cache  force a fresh download
  --all       print every name with its reject reasons (diagnostics)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import CONFIG
from screener.data import fetch_many
from screener.trend_template import (
    evaluate_trend_template,
    rs_rank_universe,
)
from screener.universe import get_universe
from screener.vcp import analyse_vcp

OUT_DIR = Path(__file__).resolve().parent / "data"


def dollar_volume_ok(df: pd.DataFrame) -> tuple[bool, float]:
    cfg = CONFIG.liquidity
    if len(df) < cfg.dollar_volume_days:
        return False, float("nan")
    tail = df.iloc[-cfg.dollar_volume_days :]
    adv = float((tail["Close"] * tail["Volume"]).mean())
    return adv >= cfg.min_dollar_volume, adv


def run(use_cache: bool = True, show_all: bool = False) -> dict:
    universe = get_universe()
    print(f"Universe: {len(universe)} names. Fetching ({CONFIG.history_period}) ...")
    data = fetch_many(universe, use_cache=use_cache)
    print(f"Fetched {len(data)} names with data.\n")

    # Pass 1: liquidity + trend template; collect RS scores for ranking.
    trend_results = {}
    rs_scores = {}
    liquidity = {}
    for t, df in data.items():
        ok, adv = dollar_volume_ok(df)
        liquidity[t] = (ok, adv)
        tr = evaluate_trend_template(df)
        trend_results[t] = tr
        rs_scores[t] = tr.rs_score

    rs_ranks = rs_rank_universe(rs_scores)

    # Pass 2: apply the full gate, then VCP analysis on survivors.
    candidates = []
    diagnostics = []

    for t, df in data.items():
        liq_ok, adv = liquidity[t]
        tr = trend_results[t]
        rank = rs_ranks.get(t, float("nan"))

        gate_reasons = []
        if not liq_ok:
            gate_reasons.append("illiquid")
        gate_reasons += tr.reasons
        if not (rank == rank and rank >= CONFIG.trend.min_rs_rank):
            gate_reasons.append(f"rs_rank<{CONFIG.trend.min_rs_rank:g}")

        if gate_reasons:
            diagnostics.append((t, "GATE", gate_reasons))
            continue

        vcp = analyse_vcp(df)
        if not vcp.is_vcp:
            diagnostics.append((t, "VCP", vcp.reasons))
            continue

        last = df.iloc[-1]
        candidates.append({
            "ticker": t,
            "close": round(float(last["Close"]), 2),
            "pivot": round(vcp.pivot, 2),
            "stop": round(vcp.stop, 2),
            "pct_to_pivot": round((vcp.pivot / float(last["Close"]) - 1.0) * 100, 2),
            "risk_pct": round((1.0 - vcp.stop / vcp.pivot) * 100, 2),
            "rs_rank": round(rank, 1),
            "contractions": vcp.contractions,
            "num_contractions": vcp.num_contractions,
            "final_range_pct": round(vcp.final_range_pct * 100, 2),
            "recent_vol_ratio": round(vcp.recent_vol_ratio, 2),
            "accumulation_signals": vcp.accumulation_signals,
            "adv_usd_m": round(adv / 1e6, 1),
        })

    candidates.sort(key=lambda c: c["rs_rank"], reverse=True)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe_size": len(universe),
        "fetched": len(data),
        "num_candidates": len(candidates),
        "candidates": candidates,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "candidates.json").write_text(json.dumps(result, indent=2))

    _print_report(result, diagnostics, show_all)
    return result


def _print_report(result: dict, diagnostics: list, show_all: bool) -> None:
    cands = result["candidates"]
    print("=" * 78)
    print(f"VCP CANDIDATES: {len(cands)}")
    print("=" * 78)
    if cands:
        hdr = f"{'TICK':<6}{'CLOSE':>9}{'PIVOT':>9}{'STOP':>9}{'%PIV':>7}{'RISK%':>7}{'RS':>6}{'CONTRACTIONS':>22}"
        print(hdr)
        print("-" * len(hdr))
        for c in cands:
            contr = ",".join(f"{d*100:.0f}" for d in c["contractions"])
            print(f"{c['ticker']:<6}{c['close']:>9.2f}{c['pivot']:>9.2f}{c['stop']:>9.2f}"
                  f"{c['pct_to_pivot']:>7.1f}{c['risk_pct']:>7.1f}{c['rs_rank']:>6.0f}{contr:>22}")
    print()
    if show_all:
        print("DIAGNOSTICS (reject reasons):")
        for t, stage, reasons in sorted(diagnostics):
            print(f"  {t:<6} [{stage}] {', '.join(reasons)}")
    print(f"\nWritten: {OUT_DIR / 'candidates.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cache", action="store_true", help="force fresh download")
    ap.add_argument("--all", action="store_true", help="print reject diagnostics")
    args = ap.parse_args()
    run(use_cache=not args.no_cache, show_all=args.all)

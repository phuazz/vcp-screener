# VCP Screener — Minervini-style Volatility Contraction Pattern signal

A rules-based screen for Mark Minervini's Volatility Contraction Pattern (VCP),
sitting on top of his Trend Template prefilter. A personal research signal. The
screen is fully systematic: no parameter is tuned per name at
runtime, and the parameter block in `config.py` is the strategy definition.

Status: **working prototype** (data layer, swing detection, Trend Template
gate, contraction analysis, candidate emission). Validated by synthetic unit
tests and by-eye diagnostics over a 47-name liquid seed. Not yet a production
signal — see Roadmap.

## What it does

For each name in the universe, per nightly run:

1. **Fetch** EOD OHLCV (split- and dividend-adjusted) — `screener/data.py`.
2. **Liquidity floor** — 50-day average dollar volume must clear the threshold.
3. **Trend Template gate** — the eight Minervini Stage 2 conditions, plus a
   cross-sectional relative-strength rank (`screener/trend_template.py`). This
   gate does most of the filtering and is intentionally restrictive.
4. **VCP analysis** — isolate the base, measure the contraction sequence,
   check volume dryness and accumulation, locate the pivot and stop
   (`screener/vcp.py`).
5. **Emit** a candidate list to `data/candidates.json` with pivot, stop,
   percentage-to-pivot, risk-to-stop, RS rank, and the contraction depths.

The four VCP elements map directly onto the code:

| Element (Badar / Minervini)        | Where                                   |
| ----------------------------------- | --------------------------------------- |
| 1. Contracting swings               | `vcp._contraction_depths` + tightening test |
| 2. Signs of accumulation            | `vcp._accumulation_signals` (pocket pivots, strong-volume up days) |
| 3. Dry volume on the right          | recent-vs-base volume ratio in `analyse_vcp` |
| 4. Final contraction                | final-leg depth + tight-range test      |

## The load-bearing piece: swing detection

`screener/swings.py` detects pivots with a ZigZag rule — a reversal is only
confirmed once price retraces at least `reversal_pct` (default 5 per cent) from
the running extreme. This makes the legs directly comparable as percentage
contractions, which is exactly what VCP measures. The base is then isolated by
anchoring at the highest swing high in the lookback window and measuring
contractions only from that high forward, so the prior uptrend's legs are not
miscounted as contractions.

This module is where the screen lives or dies; everything downstream is
arithmetic on its output. It is covered by a synthetic unit test (a constructed
contracting series) and the threshold is validated by eye, not optimised.

## Run it

```
pip install -r requirements.txt
python run_screen.py            # screen the seed universe (uses cache)
python run_screen.py --no-cache # force fresh downloads
python run_screen.py --all      # print per-name reject diagnostics
```

## Known limitations (read before trusting output)

- **Fixed swing threshold is blind to sub-threshold final contractions.** A 5
  per cent ZigZag cannot see a 3-4 per cent final contraction — yet the tight
  final squeeze is the defining feature of a clean VCP. This is the single most
  important tuning axis. Options for v2: a smaller threshold (re-fragments the
  early base), an adaptive/decreasing threshold down the base, or detecting the
  final contraction via ATR/range rather than ZigZag (already partially done
  via the tight-range test). Do not change `reversal_pct` without re-validating
  by eye.
- **Base-start is the window high.** v1 anchors the base at the highest swing
  high in the lookback. For a Trend-Template name (within 25 per cent of its
  52-week high) this is sound. It would mis-anchor a name that topped long ago
  and is basing far below — but such names fail the trend gate anyway.
- **Prototype data source.** yfinance has no delisted history and unreliable
  adjustments. It is fine for building and by-eye validation; it must never be
  the production source.

## Roadmap

1. **Wire the live Russell 1000.** `universe.load_iwb_holdings` already parses
   the iShares IWB holdings CSV; connect the download and swap it in for the
   seed list.
2. **Production data → Norgate.** Survivorship-bias-free, point-in-time index
   constituents, Windows-native Python SDK. Replaces yfinance for both the live
   screen and any historical work.
3. **Live-forward paper-track ledger.** Append one row per flagged breakout
   (entry, pivot, stop, date) and mark to market nightly. This is the primary
   evidence base — a clean out-of-sample record with no look-ahead and no
   survivorship problem — and it mirrors the ledger-first pattern used in the
   Portfolio Command Centre.
4. **Indicative historical backtest (secondary, labelled).** Only after Norgate
   is in place. Treat as indicative, never as a deployment input.

## Three ways this could be silently wrong

- **Look-ahead in the pivot.** The pivot must be fixed using only data
  available at the decision point. The breakout/entry logic (not yet built)
  must not peek at bars after entry.
- **Survivorship.** Screening today's constituents over history only finds the
  names that survived. Mitigated structurally by running live-forward first;
  for any historical run, point-in-time data (Norgate) is mandatory.
- **Unrealistic breakout fills.** Breakouts gap. Assuming a fill at the pivot
  rather than 2-3 per cent higher, and ignoring the high false-breakout rate in
  choppy tape, inflates the edge. Cost and slippage on the breakout bar matter
  more here than for slower strategies.

## Layout

```
config.py                 # strategy spec — the parameter block IS the strategy
run_screen.py             # orchestrator -> data/candidates.json
screener/
  universe.py             # seed universe + IWB holdings parser
  data.py                 # yfinance fetch + parquet cache
  swings.py               # ZigZag swing detection (load-bearing)
  trend_template.py       # Minervini Trend Template + RS rank
  vcp.py                  # base isolation, contraction analysis, pivot/stop
```

Last updated: 2026-06-14.

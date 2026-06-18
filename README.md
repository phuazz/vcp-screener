# VCP Screener — Minervini-style Volatility Contraction Pattern signal

A rules-based screen for Mark Minervini's Volatility Contraction Pattern (VCP),
sitting on top of his Trend Template prefilter. A personal research signal. The
screen is fully systematic: no parameter is tuned per name at
runtime, and the parameter block in `config.py` is the strategy definition.

Status: **research complete (technical track).** The screener and an audited,
out-of-sample-validated backtest are built. The conclusion (see "Key findings")
is that the mechanical VCP system is a genuine low-drawdown *sleeve* and a useful
idea-generation screen, but not a standalone index-beater. Adopted use is the
live screen as a watchlist plus a defensive sleeve; the technical parameter
search is finished. A genuine return edge would require the structural levers in
the Roadmap (fundamental overlay, point-in-time data), which are a data project,
not more tuning.

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
python run_backtest.py          # indicative historical backtest -> data/backtest.json
python scripts/pipeline.py      # build docs/index.html from template + both datasets
```

The dashboard (`docs/index.html`, published via GitHub Pages) shows the live
screen, the watchlist, and the backtest visuals — equity curve versus the Russell
1000 (IWB), drawdown, the out-of-sample validation table, calendar-year returns,
the R-multiple distribution, an annotated example trade, and the full trade list.
The nightly Action refreshes the screen;
the backtest changes slowly and is rebuilt occasionally with `run_backtest.py`.

## Backtest (indicative only)

`screener/backtest.py` runs a walk-forward, event-driven, portfolio-level
simulation. At each bar the base and pivot are detected from prior data only;
the breakout fills from a later bar's own range; stops and slippage are modelled
so gaps are not assumed away. Rules: enter on a breakout above the pivot; initial
hard stop at the last contraction low; then hold while the Stage 2 uptrend is
intact, exiting on a close below the 200-day average (so a multi-month run is one
trade rather than a string of clipped exits); fixed-fractional risk sizing with a
portfolio concurrency cap; idle cash earns a conservative yield. Selection uses
the same cross-sectional top-decile RS rank and dollar-volume liquidity floor as
the live screen, plus three toggleable quality filters in front — breakout-volume
confirmation, RS-ranked entries, and a market-regime gate. Sharpe and Sortino are
computed in excess of the risk-free rate; metrics are reported for an in-sample
train window and an untouched holdout. All parameters live in `BacktestConfig` in
`config.py`.

**It is indicative only.** It runs over the *current* universe on yfinance data,
so it is survivorship- and selection-biased. The three failure modes are stated
on the dashboard and in "Three ways this could be silently wrong" below. Read the
numbers as a sanity check on the rules, never as a forward return estimate.

**Universe and benchmark.** The universe is the S&P 500 + S&P 400 constituents
(~900 of the largest US names, scraped from Wikipedia and cached) as a Russell
1000 proxy; drop an official `data/iwb_holdings.csv` to override it with the real
constituents. The buy-and-hold benchmark is IWB (iShares Russell 1000).

**Key findings (the full research arc, 2017-2026 window).** Every lever was
tested and the data was allowed to overturn the hypothesis at each step:

1. *Selection bias.* The curated 47-name seed looked strong (PF ~2.1, +0.5R). On
   the broad ~900-name universe the edge collapsed (PF ~1.2, +0.1R, CAGR ~3%,
   drawdown ~ the index's). Much of the seed's apparent edge was selection bias —
   it was today's leaders.
2. *Period is not the excuse.* Momentum worked superbly this decade — MTUM ~17%
   CAGR, equal-weight (RSP) ~12%, cap-weight (IWB) ~15%. The premium was there;
   the implementation was not capturing it.
3. *Trade management was the wound.* A 50-day trailing exit churned multi-hundred-
   percent runs into many small ~+16% trades. A Stage 2 hold (exit on a close
   below the 200-day) roughly doubled the result — "let winners run" was the
   missing discipline.
4. *Selection is the real lever.* Reconciling to the screen's top-decile RS rank
   plus a liquidity floor lifted per-trade quality sharply — profit factor 2.61,
   expectancy +0.70R across 145 trades. A genuine trade-level edge.
5. *But it is regime-dependent and not an index-beater.* Out-of-sample, the
   strategy underperformed IWB on return in BOTH windows (train CAGR 2% vs 10%,
   holdout 17% vs 22%) and was near-flat for the first 5.4 years (train Sharpe
   0.05). The attractive figures are concentrated in the 2022-2026 bull, and the
   holdout is itself survivorship-inflated.
6. *Concentration is over-betting.* Doubling per-trade risk (1.5% / 6 slots)
   doubled drawdown (-19% -> -37%) for no extra return and a lower Sharpe
   (0.43 -> 0.38). Variance drag cancels the benefit; the conservative 0.75%/8
   settings are strictly better. Reverted.
7. *Price-only refinements (from the Minervini Markets 360 status bar), ablated.*
   Composite setup-quality ranking (RS + tightness + dryness) is a genuine, modest
   improvement that holds out of sample (PF 2.80 -> 3.06, holdout Sharpe 0.95 ->
   1.01) — KEPT. The extension rules (skip extended entries, trim into strength)
   were catastrophic (PF -> 1.32) because they mechanically reject the explosive
   gap-and-go breakouts that are the edge — his +/-20dma metric needs a
   discretionary intraday entry to work — REJECTED.

**Conclusion.** VCP-the-pattern is timing, not alpha. Built and audited properly
the mechanical system is a real low-drawdown sleeve with a genuine trade-level
selection edge, but long-only at moderate exposure it does not beat a strong
cap-weighted index, and its returns are regime-dependent. The technical parameter
search is exhausted. A credible standalone return edge would require the
structural levers — the fundamental overlay (Minervini's SEPA) and point-in-time
data — which are a data project, not more tuning. Adopted use: the live screen as
an idea-generation watchlist, and the strategy as a defensive sleeve if deployed.

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
config.py                 # strategy + backtest spec — the parameter block IS the strategy
run_screen.py             # screen orchestrator -> data/candidates.json
run_backtest.py           # backtest runner -> data/backtest.json
template.html             # dashboard source (Plotly), with fetch fallback
scripts/pipeline.py       # inject both datasets into docs/index.html
screener/
  universe.py             # seed universe + IWB holdings parser
  data.py                 # yfinance fetch + parquet cache
  swings.py               # ZigZag swing detection (load-bearing)
  trend_template.py       # Minervini Trend Template + RS rank
  vcp.py                  # base isolation, contraction analysis, pivot/stop
  backtest.py             # walk-forward portfolio simulation + metrics
```

Last updated: 2026-06-15.

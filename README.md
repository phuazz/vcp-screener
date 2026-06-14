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
python run_backtest.py          # indicative historical backtest -> data/backtest.json
python scripts/pipeline.py      # build docs/index.html from template + both datasets
```

The dashboard (`docs/index.html`, published via GitHub Pages) shows the live
screen, the watchlist, and the backtest visuals — equity curve versus SPY,
drawdown, calendar-year returns, the R-multiple distribution, an annotated
example trade, and the full trade list. The nightly Action refreshes the screen;
the backtest changes slowly and is rebuilt occasionally with `run_backtest.py`.

## Backtest (indicative only)

`screener/backtest.py` runs a walk-forward, event-driven, portfolio-level
simulation. At each bar the base and pivot are detected from prior data only;
the breakout fills from a later bar's own range; stops and slippage are modelled
so gaps are not assumed away. Rules: enter on a breakout above the pivot; initial
hard stop at the last contraction low; then hold while the Stage 2 uptrend is
intact, exiting on a close below the 200-day average (so a multi-month run is one
trade rather than a string of clipped exits); fixed-fractional risk sizing with a
portfolio concurrency cap; idle cash earns a conservative yield. Three toggleable
quality filters — breakout-volume confirmation, RS-ranked entries, and a
market-regime gate — sit in front. All parameters live in `BacktestConfig` in
`config.py`.

**It is indicative only.** It runs over the *current* universe on yfinance data,
so it is survivorship- and selection-biased. The three failure modes are stated
on the dashboard and in "Three ways this could be silently wrong" below. Read the
numbers as a sanity check on the rules, never as a forward return estimate.

**Universe and benchmark.** The universe is the S&P 500 + S&P 400 constituents
(~900 of the largest US names, scraped from Wikipedia and cached) as a Russell
1000 proxy; drop an official `data/iwb_holdings.csv` to override it with the real
constituents. The buy-and-hold benchmark is IWB (iShares Russell 1000).

**Key findings (be honest about these), 2017-2026 window:**

- *Selection bias.* The curated 47-name seed looked strong (PF ~2.1, +0.5R). On
  the broad ~900-name universe the edge largely collapses (PF ~1.2, +0.1R, CAGR
  ~3%) and drawdown widens to roughly the index's. Much of the seed's apparent
  edge was selection bias — it was today's leaders.
- *Period is not the excuse.* Momentum worked superbly this decade: a systematic
  momentum ETF (MTUM) returned ~17% CAGR, equal-weight (RSP) ~12%, cap-weight
  (IWB) ~15%. The premium was available; the implementation was not capturing it.
- *Trade management was the wound.* A 50-day trailing exit churned multi-hundred-
  percent runs into many small ~+16% trades. Switching to a Stage 2 hold (exit on
  a close below the 200-day) roughly doubled the result — average win ~+38%,
  expectancy +0.29R, CAGR ~7% — confirming "let winners run" was the missing
  discipline.
- *Still not an index-beater.* Even after the fix, ~7% CAGR trails passive
  momentum. The remaining gap points to what is genuinely missing: tighter
  leadership selection, concentration/sizing, and above all the fundamental
  overlay (Minervini's actual SEPA edge) on point-in-time data. The chart pattern
  alone is a timing tool, not the source of the edge.

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

Last updated: 2026-06-14.

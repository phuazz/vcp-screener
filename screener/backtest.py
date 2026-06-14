"""
Indicative historical backtest of the VCP strategy.

Walk-forward, event-driven, portfolio-level. At each bar the base and pivot are
detected using only prior data; the breakout fills only from a later bar's own
range; stops and slippage are modelled so gaps are not assumed away.

This is INDICATIVE ONLY. It runs over the current seed universe on yfinance
data, which is survivorship- and selection-biased (the names are in the sample
because they already won). The numbers sanity-check the rules; they are not a
deployment input. See README and the dashboard caveats.

Trade lifecycle:
  - Setup: while flat, when the Trend Template and an RS-vs-benchmark gate pass,
    run the VCP detector on the trailing window. A valid base with a pivot above
    the current close (and within reach) arms a pending breakout.
  - Entry: on a subsequent bar whose high crosses the pivot, fill at the pivot
    (or the open if it gapped above), plus entry slippage and commission.
  - Exit: the initial hard stop is the last contraction low; after a short grace
    period the position also trails on a close below the trailing EMA. The first
    trigger wins. Stops fill at the worse of (stop, gap-down open).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
import yfinance as yf

from config import CONFIG
from .vcp import analyse_vcp
from .swings import detect_swings
from .data import fetch_bulk


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------

def _fetch(ticker: str, period: str) -> pd.DataFrame:
    try:
        df = yf.download(ticker, period=period, interval="1d",
                         auto_adjust=True, progress=False, threads=False)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


# ----------------------------------------------------------------------------
# Indicators and gates (vectorised, look-ahead free)
# ----------------------------------------------------------------------------

def _prepare(df: pd.DataFrame, bench_close: pd.Series) -> pd.DataFrame:
    """Attach the Trend Template booleans, trailing EMA, and the RS gate."""
    t = CONFIG.trend
    bt = CONFIG.backtest
    c = df["Close"]

    sma50 = c.rolling(t.sma_short).mean()
    sma150 = c.rolling(t.sma_mid).mean()
    sma200 = c.rolling(t.sma_long).mean()
    high252 = c.rolling(252, min_periods=252).max()
    low252 = c.rolling(252, min_periods=252).min()

    trend_ok = (
        (c > sma150) & (c > sma200) & (sma150 > sma200)
        & (sma200 > sma200.shift(t.sma_long_rising_days))
        & (sma50 > sma150) & (c > sma50)
        & ((c / low252 - 1.0) >= t.min_pct_above_52w_low)
        & ((high252 / c - 1.0) <= t.max_pct_below_52w_high)
    )

    # RS gate: name outperforms the benchmark over the trailing window.
    bench = bench_close.reindex(df.index).ffill()
    L = bt.rs_lookback
    name_ret = c / c.shift(L) - 1.0
    bench_ret = bench / bench.shift(L) - 1.0
    rs_ok = name_ret > bench_ret

    df = df.copy()
    df["ma_trail"] = c.rolling(bt.trail_ma_len).mean()
    df["setup_ok"] = (trend_ok & rs_ok).fillna(False)
    return df


# ----------------------------------------------------------------------------
# Portfolio simulation
# ----------------------------------------------------------------------------

@dataclass
class Trade:
    ticker: str
    entry_date: pd.Timestamp
    entry: float
    stop0: float
    exit_date: pd.Timestamp
    exit: float
    shares: int
    return_pct: float
    r_multiple: float
    bars: int
    reason: str


def run_backtest(universe: list[str]) -> dict:
    bt = CONFIG.backtest
    vcfg = CONFIG.vcp

    bench_raw = _fetch(bt.benchmark, bt.history_period)
    if bench_raw.empty:
        raise SystemExit("Could not fetch benchmark data.")
    bench_close = bench_raw["Close"]
    calendar = bench_raw.index

    # Bulk-fetch the universe (threaded, cached), then prepare each name
    # aligned to the benchmark calendar.
    raw_data = fetch_bulk(universe, bt.history_period)
    prepared: dict[str, pd.DataFrame] = {}
    for t, raw in raw_data.items():
        if len(raw) < vcfg.base_lookback_days + 30:
            continue
        prep = _prepare(raw, bench_close).reindex(calendar)
        prepared[t] = prep

    # Numpy views for the hot loop.
    arrs = {}
    for t, d in prepared.items():
        arrs[t] = {
            "o": d["Open"].to_numpy(), "h": d["High"].to_numpy(),
            "l": d["Low"].to_numpy(), "c": d["Close"].to_numpy(),
            "trail": d["ma_trail"].to_numpy(), "setup": d["setup_ok"].to_numpy(),
            "df": d,
        }

    cash = bt.initial_equity
    positions: dict[str, dict] = {}
    pending: dict[str, dict] = {}
    trades: list[Trade] = []
    equity_dates, equity_vals = [], []

    n = len(calendar)
    warmup = 260  # need 252-day high/low plus margin
    daily_cash_yield = (1 + bt.cash_yield_annual) ** (1 / 252) - 1

    for i in range(warmup, n):
        # ---- 0. Idle cash accrues a money-market yield ----------------------
        cash *= (1 + daily_cash_yield)

        # ---- 1. Exits on today's bar ----------------------------------------
        for t in list(positions.keys()):
            a = arrs[t]
            lo, op, cl, trail = a["l"][i], a["o"][i], a["c"][i], a["trail"][i]
            if np.isnan(cl):
                continue
            pos = positions[t]
            bars_held = i - pos["entry_i"]
            exit_price = None
            reason = None
            if not np.isnan(lo) and lo <= pos["stop"]:
                # Stop hit; fill at the worse of stop or a gap-down open.
                exit_price = min(pos["stop"], op) if not np.isnan(op) else pos["stop"]
                reason = "stop"
            elif bars_held >= bt.exit_grace_bars and not np.isnan(trail) and cl < trail:
                exit_price = cl
                reason = "trail_ma"
            if exit_price is not None:
                proceeds = exit_price * (1 - bt.exit_slippage - bt.commission)
                cash += pos["shares"] * proceeds
                entry_net = pos["entry_net"]
                ret = proceeds / entry_net - 1.0
                r = ((exit_price - pos["entry_gross"]) /
                     (pos["entry_gross"] - pos["stop0"])
                     if pos["entry_gross"] > pos["stop0"] else float("nan"))
                trades.append(Trade(
                    ticker=t, entry_date=pos["entry_date"], entry=round(pos["entry_gross"], 2),
                    stop0=round(pos["stop0"], 2), exit_date=calendar[i], exit=round(exit_price, 2),
                    shares=pos["shares"], return_pct=round(ret * 100, 2),
                    r_multiple=round(r, 2) if r == r else None, bars=bars_held, reason=reason))
                del positions[t]

        # ---- 2. Entries from armed breakouts --------------------------------
        equity_now = cash + sum(positions[t]["shares"] * arrs[t]["c"][i]
                                for t in positions if not np.isnan(arrs[t]["c"][i]))
        for t in list(pending.keys()):
            if t in positions:
                pending.pop(t, None)
                continue
            p = pending[t]
            p["bars_left"] -= 1
            a = arrs[t]
            hi, op = a["h"][i], a["o"][i]
            if not np.isnan(hi) and hi >= p["pivot"] and len(positions) < bt.max_positions:
                gross = max(p["pivot"], op) if not np.isnan(op) else p["pivot"]
                entry_net = gross * (1 + bt.entry_slippage + bt.commission)
                risk_cap = bt.risk_per_trade * equity_now
                per_share_risk = gross - p["stop"]
                if per_share_risk <= 0:
                    pending.pop(t, None)
                    continue
                shares = int(risk_cap / per_share_risk)
                shares = min(shares, int(bt.max_position_pct * equity_now / entry_net))
                shares = min(shares, int(cash / entry_net))
                if shares > 0:
                    cash -= shares * entry_net
                    positions[t] = {
                        "shares": shares, "entry_gross": gross, "entry_net": entry_net,
                        "stop": p["stop"], "stop0": p["stop"], "entry_date": calendar[i],
                        "entry_i": i,
                    }
                pending.pop(t, None)
            elif p["bars_left"] <= 0:
                pending.pop(t, None)

        # ---- 3. Detection: arm pending breakouts for flat names -------------
        for t, a in arrs.items():
            if t in positions or t in pending:
                continue
            if not a["setup"][i]:
                continue
            cl = a["c"][i]
            if np.isnan(cl):
                continue
            window = a["df"].iloc[i - vcfg.base_lookback_days + 1: i + 1]
            res = analyse_vcp(window)
            if not res.is_vcp:
                continue
            pivot, stop = res.pivot, res.stop
            if not (pivot > cl and pivot <= cl * (1 + bt.max_pivot_distance) and stop < pivot):
                continue
            pending[t] = {"pivot": pivot, "stop": stop, "bars_left": bt.setup_expiry_bars}

        # ---- 4. Mark to market ---------------------------------------------
        mv = sum(positions[t]["shares"] * arrs[t]["c"][i]
                 for t in positions if not np.isnan(arrs[t]["c"][i]))
        equity_dates.append(calendar[i])
        equity_vals.append(cash + mv)

    return _assemble(universe, prepared, calendar, warmup,
                     equity_dates, equity_vals, bench_raw, trades)


# ----------------------------------------------------------------------------
# Metrics and output assembly
# ----------------------------------------------------------------------------

def _series_metrics(equity: pd.Series) -> dict:
    rets = equity.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    total = equity.iloc[-1] / equity.iloc[0] - 1.0
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1.0 if years > 0 else float("nan")
    vol = rets.std() * math.sqrt(252)
    sharpe = (rets.mean() * 252) / vol if vol > 0 else float("nan")
    downside = rets[rets < 0].std() * math.sqrt(252)
    sortino = (rets.mean() * 252) / downside if downside > 0 else float("nan")
    roll_max = equity.cummax()
    dd = equity / roll_max - 1.0
    max_dd = dd.min()
    calmar = cagr / abs(max_dd) if max_dd < 0 else float("nan")
    return {"total_return": total, "cagr": cagr, "vol": vol, "sharpe": sharpe,
            "sortino": sortino, "max_dd": max_dd, "calmar": calmar, "dd_series": dd}


def _assemble(universe, prepared, calendar, warmup, eq_dates, eq_vals,
              bench_raw, trades) -> dict:
    bt = CONFIG.backtest
    equity = pd.Series(eq_vals, index=pd.DatetimeIndex(eq_dates))

    # Benchmark buy-and-hold over the same window, scaled to initial equity.
    bench = bench_raw["Close"].reindex(equity.index).ffill()
    bench_eq = bench / bench.iloc[0] * bt.initial_equity

    m = _series_metrics(equity)
    bm = _series_metrics(bench_eq)

    # Trade statistics.
    rets = [t.return_pct for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    rs = [t.r_multiple for t in trades if t.r_multiple is not None]
    win_rate = len(wins) / len(trades) if trades else float("nan")
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("nan")
    expectancy_r = (sum(rs) / len(rs)) if rs else float("nan")
    avg_win = (sum(wins) / len(wins)) if wins else float("nan")
    avg_loss = (sum(losses) / len(losses)) if losses else float("nan")
    avg_bars = (sum(t.bars for t in trades) / len(trades)) if trades else float("nan")

    # Exposure: fraction of days with at least one position (approx via trades).
    invested_days = sum(t.bars for t in trades)
    exposure = invested_days / (len(equity) * bt.max_positions) if len(equity) else float("nan")

    # Annual returns, strategy vs benchmark.
    yr_strat = equity.resample("YE").last().pct_change()
    yr_strat.iloc[0] = equity.resample("YE").last().iloc[0] / bt.initial_equity - 1.0
    yr_bench = bench_eq.resample("YE").last().pct_change()
    yr_bench.iloc[0] = bench_eq.resample("YE").last().iloc[0] / bt.initial_equity - 1.0

    example = _example_trade(prepared, trades)

    def f(x, nd=4):
        return None if (x is None or (isinstance(x, float) and math.isnan(x))) else round(float(x), nd)

    return {
        "meta": {
            "period": bt.history_period, "benchmark": bt.benchmark,
            "start": str(equity.index[0].date()), "end": str(equity.index[-1].date()),
            "initial_equity": bt.initial_equity, "names_traded": len(prepared),
            "universe_size": len(universe),
            "risk_per_trade": bt.risk_per_trade, "max_positions": bt.max_positions,
            "entry_slippage": bt.entry_slippage, "exit_slippage": bt.exit_slippage,
            "commission": bt.commission, "trail_ma_len": bt.trail_ma_len,
            "cash_yield_annual": bt.cash_yield_annual,
        },
        "kpis": {
            "cagr": f(m["cagr"]), "total_return": f(m["total_return"]),
            "vol": f(m["vol"]), "sharpe": f(m["sharpe"], 2), "sortino": f(m["sortino"], 2),
            "max_dd": f(m["max_dd"]), "calmar": f(m["calmar"], 2),
            "num_trades": len(trades), "win_rate": f(win_rate),
            "profit_factor": f(profit_factor, 2), "expectancy_r": f(expectancy_r, 2),
            "avg_win_pct": f(avg_win, 2), "avg_loss_pct": f(avg_loss, 2),
            "avg_bars": f(avg_bars, 1), "exposure": f(exposure),
            "bench_cagr": f(bm["cagr"]), "bench_sharpe": f(bm["sharpe"], 2),
            "bench_total_return": f(bm["total_return"]), "bench_max_dd": f(bm["max_dd"]),
        },
        "equity": {
            "dates": [str(d.date()) for d in equity.index],
            "strategy": [round(v, 1) for v in equity.tolist()],
            "bench": [round(v, 1) for v in bench_eq.tolist()],
            "drawdown": [round(v, 4) for v in m["dd_series"].tolist()],
        },
        "annual": {
            "years": [str(d.year) for d in yr_strat.index],
            "strategy": [f(v) for v in yr_strat.tolist()],
            "bench": [f(v) for v in yr_bench.tolist()],
        },
        "r_multiples": [t.r_multiple for t in trades if t.r_multiple is not None],
        "trades": [vars(t) | {"entry_date": str(t.entry_date.date()),
                              "exit_date": str(t.exit_date.date())} for t in trades],
        "example": example,
    }


def _example_trade(prepared, trades) -> dict | None:
    """Pick the highest-R trade and emit its price window with annotations."""
    candidates = [t for t in trades if t.r_multiple is not None]
    if not candidates:
        return None
    best = max(candidates, key=lambda t: t.r_multiple)
    df = prepared.get(best.ticker)
    if df is None:
        return None
    df = df.dropna(subset=["Close"])
    try:
        entry_pos = df.index.get_loc(best.entry_date)
        exit_pos = df.index.get_loc(best.exit_date)
    except KeyError:
        return None
    lo = max(0, entry_pos - 90)
    hi = min(len(df), exit_pos + 12)
    win = df.iloc[lo:hi]
    # Swings as detected at the entry bar (base context for the chart).
    base = df.iloc[max(0, entry_pos - CONFIG.vcp.base_lookback_days + 1): entry_pos + 1]
    sw = detect_swings(base, CONFIG.swing.reversal_pct)
    return {
        "ticker": best.ticker,
        "dates": [str(d.date()) for d in win.index],
        "open": [round(float(x), 2) for x in win["Open"]],
        "high": [round(float(x), 2) for x in win["High"]],
        "low": [round(float(x), 2) for x in win["Low"]],
        "close": [round(float(x), 2) for x in win["Close"]],
        "pivot": round(best.entry, 2), "stop": round(best.stop0, 2),
        "entry_date": str(best.entry_date.date()), "entry": round(best.entry, 2),
        "exit_date": str(best.exit_date.date()), "exit": round(best.exit, 2),
        "r_multiple": best.r_multiple, "return_pct": best.return_pct,
        "swings": [{"date": str(s.date.date()), "price": round(s.price, 2), "kind": s.kind}
                   for s in sw],
    }

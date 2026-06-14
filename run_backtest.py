"""
Run the indicative VCP backtest over the seed universe and write
data/backtest.json for the dashboard.

    python run_backtest.py

Indicative only: survivorship- and selection-biased (current seed names on
yfinance). See README and the dashboard caveats.
"""

from __future__ import annotations

import json
from pathlib import Path

from screener.backtest import run_backtest
from screener.universe import get_universe

OUT = Path(__file__).resolve().parent / "data" / "backtest.json"


def main() -> None:
    result = run_backtest(get_universe())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result), encoding="utf-8")
    k = result["kpis"]
    print(f"Backtest {result['meta']['start']} -> {result['meta']['end']} "
          f"({result['meta']['names_traded']} names)")
    print(f"  trades {k['num_trades']} | win {k['win_rate']:.0%} | "
          f"PF {k['profit_factor']} | expectancy {k['expectancy_r']}R")
    print(f"  CAGR {k['cagr']:.1%} | Sharpe {k['sharpe']} | maxDD {k['max_dd']:.1%} "
          f"| vs SPY CAGR {k['spy_cagr']:.1%} Sharpe {k['spy_sharpe']}")
    print(f"  Wrote {OUT}")


if __name__ == "__main__":
    main()

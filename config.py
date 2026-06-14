"""
Strategy specification for the Minervini-style VCP screener.

This module is the single source of truth for every threshold the screen uses.
It is deliberately verbose: in a Navigo research context this parameter block
IS the strategy definition. Changing a number here changes the strategy, and
every change should be logged in the README changelog with a dated rationale.

No parameter is tuned per name at runtime. The screen is fully rules-based.

References:
  - Minervini, "Trade Like a Stock Market Wizard" (Trend Template, VCP).
  - The four VCP elements as summarised by Haseeb Badar (@hb_stocks):
    contracting swings, signs of accumulation, dry volume on the right,
    final contraction.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TrendTemplateConfig:
    """Minervini Trend Template — the Stage 2 uptrend prefilter.

    This gate does most of the work. A name must be in a confirmed uptrend
    before a VCP base is even considered, otherwise the pattern fires in
    downtrends, which is exactly what it is not for.
    """

    # Moving-average lookbacks in trading days.
    sma_short: int = 50
    sma_mid: int = 150
    sma_long: int = 200

    # The 200-day SMA must have been rising for at least this many days.
    sma_long_rising_days: int = 20

    # Price must sit within this fraction below the 52-week high.
    # 0.25 means "no more than 25 per cent below the 52-week high".
    max_pct_below_52w_high: float = 0.25

    # Price must sit at least this fraction above the 52-week low.
    # 0.30 means "at least 30 per cent above the 52-week low".
    min_pct_above_52w_low: float = 0.30

    # Cross-sectional relative-strength percentile floor (0-100).
    # 70 means the name must be in the top 30 per cent of the universe by RS.
    min_rs_rank: float = 70.0


@dataclass(frozen=True)
class SwingConfig:
    """Swing (pivot) detection. The load-bearing piece.

    Swings are detected with a ZigZag rule: a reversal is only recorded once
    price retraces at least `reversal_pct` from the running extreme. This makes
    the resulting swing legs directly comparable as percentage contractions,
    which is precisely what VCP measures.

    The threshold is the most sensitive parameter in the whole system. Too
    small and noise becomes contractions; too large and the tightening is
    missed. It is fixed here and validated by eye against known charts.
    """

    # Minimum percentage reversal from the running extreme to confirm a swing.
    reversal_pct: float = 0.05


@dataclass(frozen=True)
class VCPConfig:
    """Volatility-contraction-pattern detection over the detected swings."""

    # The base is searched within this trailing window (trading days).
    base_lookback_days: int = 130  # roughly six months

    # A valid VCP has between this many contractions (peak-to-trough legs).
    min_contractions: int = 2
    max_contractions: int = 6

    # Each contraction must be no deeper than the previous one times this
    # tolerance. 1.0 is strict monotonic tightening; >1 allows minor noise.
    contraction_tolerance: float = 1.10

    # The first (widest) contraction should not exceed this depth, otherwise
    # the base is too loose / too volatile to be a clean VCP.
    max_first_contraction: float = 0.35

    # The final (tightest) contraction must be no deeper than this — the
    # "looks dead" final squeeze.
    max_final_contraction: float = 0.10

    # Final-contraction range over the last `final_range_days` sessions must be
    # tighter than this fraction of price (the tight-price-range test).
    final_range_days: int = 10
    max_final_range_pct: float = 0.10


@dataclass(frozen=True)
class VolumeConfig:
    """Volume-dryness and accumulation tests."""

    # Recent average volume (last `recent_days`) must be below this fraction of
    # the base average volume — volume drying up on the right.
    recent_days: int = 10
    max_recent_vol_ratio: float = 0.80

    # Pocket-pivot / accumulation: an up-day whose volume exceeds the highest
    # down-day volume over the trailing `pocket_lookback` sessions.
    pocket_lookback: int = 10

    # A "strong rally on volume" day closes up on volume above this multiple of
    # the 50-day average volume.
    rally_vol_multiple: float = 1.5

    # Require at least this many accumulation signatures inside the base
    # (pocket pivots + strong-volume up days).
    min_accumulation_signals: int = 1


@dataclass(frozen=True)
class LiquidityConfig:
    """Tradability floor — keeps fills realistic for a fund book."""

    # 50-day average dollar volume floor, in USD.
    min_dollar_volume: float = 20_000_000.0
    dollar_volume_days: int = 50


@dataclass(frozen=True)
class RSConfig:
    """Relative-strength score used for the cross-sectional RS rank.

    IBD-style weighted return: the most recent quarter is double-weighted.
    Computed per name, then percentile-ranked across the universe.
    """

    # Quarter lengths in trading days and their weights (most recent first).
    quarter_days: int = 63
    weights: tuple = (0.40, 0.20, 0.20, 0.20)  # Q1 (recent) ... Q4


@dataclass(frozen=True)
class Config:
    """Top-level container. Import `CONFIG` elsewhere."""

    # History fetched per name. Needs comfortably more than 200 + RS lookback.
    history_period: str = "2y"
    interval: str = "1d"

    trend: TrendTemplateConfig = field(default_factory=TrendTemplateConfig)
    swing: SwingConfig = field(default_factory=SwingConfig)
    vcp: VCPConfig = field(default_factory=VCPConfig)
    volume: VolumeConfig = field(default_factory=VolumeConfig)
    liquidity: LiquidityConfig = field(default_factory=LiquidityConfig)
    rs: RSConfig = field(default_factory=RSConfig)


CONFIG = Config()

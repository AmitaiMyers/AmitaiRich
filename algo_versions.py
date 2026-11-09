"""Every algorithm version, as data. Add a version here; run it with `python strategy_lab.py run <name>`.

A version is either the production rider (v0, an existing algorithms.py strategy restricted to
the point-in-time universe) or a RankedStrategy spec:

    weights   factor -> weight; each factor is turned into a 0-1 percentile rank among the day's
              eligible stocks; composite = weighted average over the factors a stock has
              (weights renormalized when a fundamental is unknown)
    filters   hard rules a stock must pass to be bought (see strategy_lab.FILTERS)
    exits     sell rules (see strategy_lab.EXITS); the catastrophe stop always applies
    rebalance 'weekly' | 'monthly': buys (and rank-drop sells) happen only on rebalance days
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Version:
    name: str
    description: str
    weights: dict = field(default_factory=dict)
    filters: dict = field(default_factory=dict)
    exits: dict = field(default_factory=dict)
    rebalance: str = "monthly"
    max_positions: int = 20
    hold_buffer: float = 3.0          # rank-drop exit when rank > hold_buffer * max_positions
    sizing: str = "equal_weight"      # or "risk_based"
    risk_pct: float = 0.01
    atr_mult: float = 4.0             # catastrophe stop: widest of swing low / entry - atr_mult * ATR
    universe: str = "core"            # core = point-in-time S&P 500; extended adds current mid/small caps
    base_algorithm: str = None        # set => run this algorithms.py strategy instead of a ranked one
    base_config: dict = field(default_factory=dict)
    parent: str = None


V0 = Version(
    "v0", "Production Growth Momentum Rider (ROC126 > 25% & close > SMA200; exit close < SMA200), "
          "restricted to point-in-time S&P 500 members; 20 positions, 1% risk.",
    base_algorithm="Momentum Rider (ROC + MA exit)",
    base_config={"mom_lookback": 126, "mom_threshold": 0.25, "atr_period": 20},
    sizing="risk_based", rebalance="daily")

V1 = Version(
    "v1", "Owner's thesis as first written: earnings beats + growth + trend, market filter, "
          "indicator confirmation, equal-weighted top 20, monthly.",
    weights={"eps_surprise": 1.0, "beat_streak": 1.0, "sue": 1.0, "rev_growth_yoy": 1.0,
             "eps_growth_yoy": 0.5, "rev_consistency": 0.5, "eps_consistency": 0.5,
             "mom_12_1": 1.0, "vol_adj_mom": 1.0, "trend_50_200": 0.5,
             "adx_trend": 0.25, "obv_trend": 0.25, "volume_surge": 0.25},
    filters={"market_up": True, "stock_above_ma": 200},
    exits={"ma_break": 200, "rank_drop": True},
)

VERSIONS = {v.name: v for v in (V0, V1)}

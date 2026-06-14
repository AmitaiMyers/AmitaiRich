"""Risk/return analytics computed from a run's daily-equity curve.

Pure functions on a pandas equity Series (total portfolio value per bar). Used by
the research harness to enrich the headline KPIs with drawdown and risk-adjusted
measures. `periods_per_year` should match the candle interval (≈252 for daily).
"""

import numpy as np


def max_drawdown(equity):
    """Largest peak-to-trough decline as a negative fraction (e.g. -0.32 = -32%)."""
    if len(equity) < 2:
        return 0.0
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1.0
    return float(drawdown.min())


def cagr(equity, periods_per_year=252):
    """Compound annual growth rate implied by the first/last equity values."""
    if len(equity) < 2:
        return 0.0
    total_growth = equity.iloc[-1] / equity.iloc[0]
    years = len(equity) / periods_per_year
    if years <= 0 or total_growth <= 0:
        return 0.0
    return float(total_growth ** (1.0 / years) - 1.0)


def sharpe(equity, periods_per_year=252):
    """Annualized Sharpe ratio (risk-free = 0) from per-bar returns."""
    returns = equity.pct_change().dropna()
    if len(returns) < 2:
        return 0.0
    std = returns.std()
    if std == 0:
        return 0.0
    return float(np.sqrt(periods_per_year) * returns.mean() / std)

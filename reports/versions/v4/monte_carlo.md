# Monte Carlo — v4

5000 paths of 21-day blocks resampled from the development + validation daily returns (blocks keep streaks and crashes intact).

**Verdict: FRAGILE** (stable = 5-year 5th-percentile CAGR above 0 and beats SPY in at least 60% of 5-year paths).

## Outcome distribution

| horizon | P(loss) | P(beat SPY) | CAGR 5th pct | CAGR median | CAGR 95th pct | max DD median | max DD 95th worst |
|---|---|---|---|---|---|---|---|
| 1 year | 28% | 50% | -22.2% | +11.0% | +41.6% | -14% | -34% |
| 5 years | 14% | 50% | -5.1% | +9.3% | +23.7% | -29% | -51% |


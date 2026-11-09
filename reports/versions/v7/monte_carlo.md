# Monte Carlo — v7

5000 paths of 21-day blocks resampled from the development + validation daily returns (blocks keep streaks and crashes intact).

**Verdict: FRAGILE** (stable = 5-year 5th-percentile CAGR above 0 and beats SPY in at least 60% of 5-year paths).

## Outcome distribution

| horizon | P(loss) | P(beat SPY) | CAGR 5th pct | CAGR median | CAGR 95th pct | max DD median | max DD 95th worst |
|---|---|---|---|---|---|---|---|
| 1 year | 20% | 54% | -13.7% | +12.4% | +37.6% | -11% | -26% |
| 5 years | 6% | 63% | -0.5% | +11.4% | +22.9% | -21% | -40% |


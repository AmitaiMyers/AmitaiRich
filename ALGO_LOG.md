# ALGO LOG — every algorithm version and its results

One entry per version: what changed, why, development vs validation results, conclusion.
The locked holdout (2023-01-01 → today) is only opened for a final candidate; every opening is
recorded here with the date it was opened.

| Version | Date | Summary | Dev CAGR / MaxDD | Val CAGR / MaxDD | Verdict |
|---|---|---|---|---|---|
| v0 | 2026-11-09 | Production Growth Momentum Rider (ROC126 > 25% & close > SMA200; exit close < SMA200), restricted to point-in-time S&P 500 members; 20 positions, 1% risk. | +5.6% / -43% | +5.6% / -27% | see report |
| v1 | 2026-11-09 | Owner's thesis as first written: earnings beats + growth + trend, market filter, indicator confirmation, equal-weighted top 20, monthly. | +6.2% / -23% | -1.0% / -23% | FLAGS: validation CAGR -1.0% is more than a third below development +6.2%; 17 tuned components (> 15): high risk of fitting noise |
| v2 | 2026-11-09 | v1 without the market filter and with a wide (8xATR) catastrophe stop — development showed 206 of 603 exits were stop-outs (churn) and the filter sat in cash through rebounds. | +3.3% / -53% | +7.0% / -28% | FLAGS: 16 tuned components (> 15): high risk of fitting noise |
| v3 | 2026-11-09 | Earnings-led: weight only the factors with development evidence (beat streak t=3.4, SUE, revenue acceleration), keep the stock-trend filter, wide stop. | +5.9% / -50% | +8.6% / -25% | see report |
| v4 | 2026-11-09 | Post-earnings drift: buy FRESH big beats (report <= 30 days old) with a beat history, in an uptrend; weekly; exit on rank drop or a 1-year time stop. Motivated by beat_streak's 1-month edge (t=3.4) in development. | +8.5% / -56% | +9.5% / -35% | see report |
| v5 | 2026-11-09 | v3's best form (MA200 + 1-year time stop) on the EXTENDED universe (+ current S&P 400/600, Nasdaq-100, lists). Survivor-biased: judge it against the extended random control. | +4.0% / -67% | +4.9% / -29% | see report |
| v6 | 2026-11-09 | v4 without the fresh-surprise factor. Development-only reason: removing it cost 0.5%/yr but cut the development max drawdown from -56% to -24% (criterion 2: max DD <= 35%). | +8.0% / -24% | +12.7% / -30% | see report |
| v6b | 2026-11-09 | v6 with the development-best exit from the v4 SELL tournament (rank drop only, no time stop). | +8.2% / -22% | +11.8% / -32% | see report |

## Round 1 conclusions (2026-11-09)

Data: point-in-time S&P 500 (1996+), EDGAR fundamentals (1,650 companies), Yahoo consensus
surprises (119,773 reports). See reports/data/coverage.md and reports/factors/factor_report.md.

1. **Survivorship gap is large:** only 52-61% of 2004-2008 index members have Yahoo prices (92% by
   2022). Missing names skew toward failures, so every stock-level result here is biased UPWARD
   while SPY/RSP (real ETFs) are not — true edges are smaller than shown.
2. **Factors (cross-section, S&P 500):** momentum, trend, volume, Bollinger, ADX, OBV show no
   predictive edge 2005-2018. Only **beat_streak** (consistent EPS beats) is significant
   (1-month IC +0.024, t 3.4); it weakens in validation.
3. **Two machinery bugs found by random controls and fixed** (strategy_lab controls): rebalance
   buys allowed only on the rebalance day left freed cash idle (v1-v3 ~70% invested); the
   carried list then re-bought stocks just sold (churn loop). Random-20-held now tracks RSP.
4. **Exits:** fast exits (MA50, ADX/OBV weakening, tight trailing stops) destroy return; a market-
   down exit is the textbook overfit (best development, worst validation).
5. **Ablation:** several ingredients flip sign between periods (SUE, beat_streak, trend filter) —
   they fit noise. Choices were made on development only.
6. **Best so far: v6b** (beat-streak / SUE / revenue-acceleration composite, uptrend + last-beat
   filters, weekly, rank-drop exit): development 8.2% CAGR, -22% DD, Sharpe 0.68 vs SPY 7.5% /
   -55% / 0.48; validation 11.8% / -32% / 0.63 vs SPY 13.0% / -34% / 0.66. Its development edge
   comes mostly from being 65% invested (few names qualify in weak markets). Monte Carlo: FRAGILE
   vs SPY. Meets criteria 2, 4, 5, 6; misses 1 (CAGR +2pp) and 3 in validation.
7. **Holdout stays locked** — no version meets the success criteria on development + validation.

Selection-bias note: ~10 versions and ~50 variants have now been tried on the same history; treat
every development number as optimistic.

## Holdout openings

- 2026-11-09: holdout opened for **v6b** — Owner approved testing v6b (2026-11-09) after round 1; criteria 1 and 3 not met in development/validation.
  Result: v6b +8.4% CAGR / -27% max DD vs SPY +20.9% / -19%, RSP +14.2% / -18% — FAILS (reports/versions/v6b/holdout.md).

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
| v7 | 2026-11-09 | Earnings-led, concentrated: beat streak + SUE + revenue acceleration; buy only stocks in an uptrend that beat last quarter; top 10, checked weekly; sell when a holding drops out of the top 30. Chosen from a 767-config search as the centre of a robust plateau (24 neighbours: dev 7.6-10.0% CAGR, -20% to -26% max DD). | +9.9% / -22% | +14.7% / -33% | see report |

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

## Round 2 conclusions (2026-11-09)

1. **Search:** 767 configurations (reports/search/search.md), scored on development only. The
   single best development config (earnings + short-term reversal, 10.3%) collapsed to 4.0% in
   validation — selection bias made visible. The robust result is a **plateau**: the "earn3"
   family (beat streak + SUE + revenue acceleration) with 8-12 positions, weekly, uptrend filter —
   24 neighbouring settings all give 7.6-10.0% dev CAGR with -20% to -26% max DD.
2. **Ideas that did not help (development):** idle cash in SPY (the cash was bear-market
   protection: 8.2% -> 7.3%, DD -22% -> -55%); adaptive weights from trailing IC (4.1%); a size
   tilt (6.5%); momentum/rider families (best 6.5-8.2%).
3. **v7** (plateau centre: earn3, 10 positions, weekly, rank-drop exit): dev 9.9% / -22% / Sharpe
   0.77 vs SPY 7.5% / -55% / 0.48; validation 14.7% / -33% / 0.73 vs SPY 13.0% / -34% / 0.66 —
   5 of 6 criteria (misses +2pp in validation by 0.3pp). Monte Carlo borderline (5-yr 5th pct -0.5%).
4. **Holdout 2023-26:** v7 +14.0% / -30% vs SPY +20.9% / -19% (RSP +14.2%) — FAILS. Production v0
   (momentum rider, never tuned) made +21.2% / -37% there, after trailing SPY badly in 2005-22.
   Earnings quality and momentum win in opposite regimes; neither beats SPY in all three periods.
5. A 50/50 v0 + v7 blend (idea inspired by the holdout, so the holdout cannot validate it):
   2005-18 +8.1% / -24%, 2019-22 +10.7% / -30%, 2023-26 +17.8% / -33% — below SPY in the last two.
6. **The holdout has now been opened 3 times** (v6b, v7, v0). Any further candidate must be judged
   by forward paper trading (new data), not by this period.

## Decision (2026-11-09): forward paper trading

The owner chose to paper-trade **v0 and v7 side by side from 2026-11-10** ($32,000 each, rules
frozen) — the only untouched out-of-sample test left. Daily results: reports/paper/paper.md and
the PWA Research page ("paper"). Production (scan_today.py) stays v0 until the paper results
justify a change. Judge after 6-12 months at the earliest; shorter windows are mostly noise.

## Owner's idea (2026-11-10): skip buys after an extreme run-up → v0m (paper only)

Prompted by MRNA topping the v0 list at +425% 6-month momentum. v0 with entry caps, development /
validation only (holdout untouched), CAGR / max DD:

| variant | dev 2005-18 | val 2019-22 |
|---|---|---|
| v0 (no cap) | 5.6% / -43% | 5.6% / -27% |
| <= 100% above 200-MA | 5.2% / -43% | 4.9% / -27% |
| <= 75% above 200-MA | 5.6% / -43% | 3.7% / -27% |
| <= 50% above 200-MA | 5.0% / -44% | 2.2% / -27% |
| **6-mo momentum <= +200%** | **6.5% / -43%** | **6.8% / -28%** |
| 6-mo momentum <= +100% | 7.2% / -43% | 6.1% / -27% |

A cap on distance above the trend loses return (as in the June research); a cap on the run-up
itself adds ~1pp/yr in BOTH periods with the same drawdown. Small effect, two cap levels tested.
The milder +200% cap (`max_mom: 2.0`) became **v0m** and joins forward paper trading from
2026-11-10 next to v0 and v7. Production stays v0 until paper results justify a change.

## Round 3 (2026-11-11): search for a 20-25 position algorithm that beats v0 and v7 — NO WINNER

Owner's brief: higher CAGR than v0 and v7 in every test period, max DD <= 35%, 20-25 positions,
full sells, per-position stop, optional market filter; design on 2005-2022, never touch 2023+.

1. **Flaw found in the v7 record.** EDGAR fundamentals start in 2009-2010, so v7 (and every earn3
   strategy) sat in CASH until July 2009: its development "-22% max DD vs SPY -55%" came from missing
   2008 for lack of data. Fair windows from now on: crash 2005-2010 (price + Yahoo earnings only),
   dev 2011-2018, val 2019-2022.

   | | crash 2005-10 | dev 2011-18 | val 2019-22 |
   |---|---|---|---|
   | v0 | 3.9% / -43% | 5.4% / -25% | 5.6% / -27% |
   | v0m | 5.1% / -43% | 6.0% / -25% | 6.8% / -28% |
   | v7 (10 pos) | 5.0% / -17% (22% invested) | 13.0% / -21% | 16.1% / -33% |
   | v7 at 20 pos | 4.7% / -19% | 10.8% / -23% | 12.5% / -32% |
   | SPY | 2.8% / -55% | 11.1% / -19% | 13.0% / -34% |

2. **New factors, all noise** (monthly rank IC, 2005-10 and 2011-18): earnings announcement return,
   residual momentum, net-margin trend, EPS acceleration. beat_streak stays the only significant one
   (t = 3.0 in 2011-18).
3. **Search:** 600 configurations = 5 weight sets x 5 filters (incl. v0's momentum gate, with/without
   the +200% cap) x 3 exits x {20,25} positions x {weekly,monthly} x market filter {off,on}. Rule fixed
   before running: family score = median dev CAGR over its 8 neighbours; top 3 families go to
   validation once, with the best-dev neighbour that keeps the 2005-10 drawdown within -35%.
   v0's momentum gate lowered return in every family (median dev 7.9% vs 10.0% for a plain
   above-200-MA filter).
4. **Finalists (earn3 + low volatility, above 200-MA, rank-drop exit, market filter):**

   | finalist | crash | dev | val | 40 random portfolios, same rules: val 5% / median / 95% |
   |---|---|---|---|---|
   | 20 pos, weekly | 4.6% / -22% | 14.6% / -14% | **5.4% / -16%** | 2.8% / 6.3% / 9.5% |
   | +beat filter, 25 pos | 4.5% / -25% | 14.5% / -16% | **3.2% / -19%** | 2.5% / 6.2% / 9.7% |
   | +MA200 exit, 25 pos | 4.3% / -17% | 11.9% / -13% | **4.7% / -17%** | 3.7% / 7.8% / 11.3% |

   All three beat v7 in development and then fell BELOW the median random portfolio in validation.
   None beats v7 (16.1%) or even v0 (5.6%) there. **No algorithm is promoted.** The validation
   result is not used to re-tune (that would be fitting the validation period).
5. Conclusion: with free data on S&P 500 members there is one weak real signal (beat streak);
   more searching mostly finds development-period luck. v0, v0m and v7 stay in paper trading.

## Owner's question (2026-11-12): move the stop up once a position is in profit — NOT adopted

v0's stop is fixed at entry; the rising 200-day MA is its only trailing exit. Tested a stop that is
raised after the position's highest high reaches a trigger (effective from the next day), CAGR:

| rule | v0 2005-10 / 2011-18 / 2019-22 | v0m 2005-10 / 2011-18 / 2019-22 |
|---|---|---|
| no change | 3.5% / 5.0% / 6.1% | 4.7% / 5.6% / 6.1% |
| break-even after +20% | 2.9% / 6.4% / 3.3% | 3.1% / 7.1% / 5.1% |
| break-even after +30% | 3.6% / 7.8% / 5.3% | 3.9% / 7.9% / 9.1% |
| break-even after +50% | 3.5% / 6.2% / 5.7% | 4.7% / 6.6% / 7.3% |
| lock +20% after +50% | 1.9% / 4.5% / 5.3% | 2.6% / 5.0% / 6.1% |
| lock +50% after +100% | 2.3% / 6.1% / 6.2% | 2.6% / 7.2% / 6.8% |

Max drawdown is unchanged or slightly worse everywhere (-43% to -47% in 2005-10). No rule helps in
all three periods on both strategies, and neighbouring triggers (+20% / +30% / +50%) disagree in
sign — the +30% result is noise, not an edge. Locking in profit clearly hurts (it sells winners on
normal pullbacks). Stops stay fixed.

## Machine-learning ranker (2026-11-12): gradient-boosted trees, walk-forward — FAILS

Pre-registered: 24 library factors as cross-sectional percentile ranks -> predict the percentile
rank of the next-21-bar return; one LightGBM model per year 2008-2022, trained only on days whose
outcome finished before that year (expanding from 2005); fixed settings (200 trees, depth 3,
lr 0.05, >= 200 rows per leaf, 70% sampling, 3 seeds averaged), nothing tuned. Portfolio: top 20
by model score above the 200-day MA, weekly, rank-drop exit (round-3 finalist structure).

| | 2008-10 | 2011-18 | 2019-22 |
|---|---|---|---|
| rank IC of the model score (t) | -0.008 (-0.6) | -0.006 (-0.4) | +0.004 (+0.3) |
| rank IC of beat_streak alone (t) | +0.014 (+0.7) | +0.026 (+3.0) | +0.009 (+0.7) |
| ML top 20 + market filter: CAGR / max DD | 7.0% / -18% | 3.6% / -35% | 4.0% / -23% |
| ML top 20, no market filter | -11.5% / -57% | 6.0% / -35% | 2.2% / -37% |
| v7 (reference) | — | 13.0% / -21% | 16.1% / -33% |

The model's out-of-sample score has NO predictive power (IC ~ 0 in all three periods) — worse than
the single hand-picked beat_streak factor it was given. It spread its weight over noise factors
(beat_streak 12% of gain, then momentum, low-vol, size ...). Below v0 in 2011-18 and 2019-22.
Not adopted; more model capacity cannot add information the inputs do not carry.

## Holdout openings

- 2026-11-09: holdout opened for **v6b** — Owner approved testing v6b (2026-11-09) after round 1; criteria 1 and 3 not met in development/validation.
  Result: v6b +8.4% CAGR / -27% max DD vs SPY +20.9% / -19%, RSP +14.2% / -18% — FAILS (reports/versions/v6b/holdout.md).
- 2026-11-09: holdout opened for **v7** — Final candidate of round 2 (767-config search, plateau centre); holdout previously opened once for v6b, not used for tuning.
  Result: v7 +14.0% CAGR / -30% max DD vs SPY +20.9% / -19%, RSP +14.2% — FAILS.
- 2026-11-09: holdout opened for **v0** — Production baseline on the same period, for an apples-to-apples production decision (v0 is fixed, never tuned).
  Result: v0 +21.2% CAGR / -37% max DD vs SPY +20.9% / -19% — about SPY's return, deeper drawdown.

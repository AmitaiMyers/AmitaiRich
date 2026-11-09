# GOAL SPEC — the active momentum + earnings strategy (Phase 0, approved 2026-11-09)

A research + signal tool (no broker, no automatic orders). Find stocks with large upside early,
hold them while they work, sell when they weaken — and prove it beats buying the S&P 500.

## Decisions (owner's answers)

| Topic | Decision |
|---|---|
| Market / universe | US stocks. Large caps (historical S&P 500) as the survivorship-controlled core; mid/small caps (S&P 400/600, Nasdaq-100, watchlist, Magic Formula) as an extended universe. |
| Capital | $32,000, as many positions as the research supports. |
| Positions | 20–25 (research decides within / around this range). |
| Rebalance / trading | Weekly or monthly (research decides); signals acted on manually at the next open. |
| Holding period | As long as the rules say (no fixed horizon). |
| Sizing, risk/position, cash-in-downtrend | Whatever the research shows is most profitable within the success criteria. |
| Data budget | Free first; paid data recommended only where it measurably fixes a bias (see Data). |
| History | As far back as the data allows (prices 2004+, fundamentals/estimates ~2005–2009+). |
| Production | Today's Growth Momentum Rider stays live and is **v0, the baseline every version must beat**. |
| Outputs | Markdown reports + charts in `reports/`, also published to the PWA Research page. |

## Definitions (as recommended, approved)

- **vol undr** = volume relative to its average (the "volume underlay" under the price chart);
  tested both as a breakout surge and as quiet-consolidation volume.
- **Consistent growth** = revenue and diluted EPS up year-over-year in each of the last 3 fiscal
  years (point-in-time, from SEC filings), plus the latest quarter's YoY growth.
- **Beat/match** = reported EPS ≥ consensus estimate at the announcement (surprise ≥ 0%);
  graded by surprise size; revenue beats are not required (no free consensus revenue history).

## Data — free sources, point-in-time rules

| Data | Source | Point-in-time rule |
|---|---|---|
| Daily OHLCV | Yahoo (yfinance), parquet cache | known at each close; trade the next open |
| S&P 500 membership | fja05680/sp500 historical components (1996→) | member on that date only |
| EPS estimate / actual / surprise | Yahoo earnings calendar (~2005→) | usable from the first close after the announcement |
| Revenue, diluted EPS (quarterly/annual) | SEC EDGAR XBRL companyfacts (~2009→) | usable from the filing date |
| Macro (rates, CPI) | FRED | usable from the release date (lagged one month for CPI) |

**Known residual bias:** Yahoo has no prices for most delisted companies, so historical S&P 500
members that later failed are partly missing. The coverage report measures how much. The paid
fix is Norgate Data (US stocks incl. delisted + historical index membership); recommended only if
the measured gap is material.

## Validation protocol (non-negotiable)

- **Development period:** 2005-01-01 → 2018-12-31 (all iteration happens here).
- **Validation period:** 2019-01-01 → 2022-12-31 (checked each round, side by side with development).
- **LOCKED holdout:** 2023-01-01 → today. Opened once, for the final candidate; every opening is logged.
- Signals use data known at the close; fills at the next open; 10 bps/side costs (+ slippage tests).
- Every report shows development vs validation side by side and flags overfitting
  (big gap, < 100 trades, too many tuned parameters).

## Success criteria (holdout, vs SPY buy & hold over the same dates)

1. CAGR ≥ SPY + 2 percentage points per year.
2. Max drawdown no worse than SPY's, and at most 35%.
3. Sharpe ≥ SPY's.
4. ≥ 100 round-trip trades.
5. Development → validation CAGR shrinkage < one third.
6. Beats v0 (production) on the same rules.

"Perfect" is not a target; these six are.

# Paper trading — v0, v0m, v7 (forward, out-of-sample)

Start 2026-11-10 with $32,000 each; rules frozen; next-open fills; 10 bps/side. Day 10 of paper trading (data to 2026-11-23).

| Account | Days | Value | Return | Max DD | Trades |
|---|---|---|---|---|---|
| v0 | 10 | $30,362 | -5.12% | -7.2% | 2 |
| v0m | 10 | $30,484 | -4.74% | -6.7% | 2 |
| v7 | 10 | $30,779 | -3.81% | -7.1% | 1 |
| BENCH SPY | 10 | $30,808 | -3.63% | -9.1% | 0 |
| BENCH RSP | 10 | $30,808 | -3.63% | -6.8% | 0 |

## v0 — Production Growth Momentum Rider (ROC126 > 25% & close > SMA200; exit close < SMA200), restricted to point-in-time S&P 500 members; 20 positions, 1% risk.

**Orders for the next open:** BUY ALLE

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MRNA | 2026-11-11 | 3 | 252.78 | 212.08 | -16.1% |
| CRL | 2026-11-11 | 4 | 347.38 | 338.26 | -2.6% |
| BBY | 2026-11-11 | 19 | 103.12 | 97.0 | -5.9% |
| CDW | 2026-11-11 | 10 | 171.86 | 170.06 | -1.0% |
| CRWD | 2026-11-11 | 5 | 235.35 | 208.97 | -11.2% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1725.52 | -2.1% |
| RVTY | 2026-11-11 | 10 | 161.07 | 151.29 | -6.1% |
| WDAY | 2026-11-11 | 10 | 190.49 | 176.08 | -7.6% |
| DLTR | 2026-11-11 | 13 | 139.88 | 139.1 | -0.6% |
| A | 2026-11-11 | 14 | 178.99 | 176.04 | -1.6% |
| IQV | 2026-11-11 | 8 | 276.89 | 251.92 | -9.0% |
| TMO | 2026-11-11 | 3 | 719.69 | 688.08 | -4.4% |
| MPC | 2026-11-11 | 3 | 394.85 | 357.69 | -9.4% |
| ACN | 2026-11-11 | 7 | 255.18 | 222.29 | -12.9% |
| TECH | 2026-11-11 | 62 | 72.75 | 72.8 | +0.1% |
| VEEV | 2026-11-20 | 7 | 259.25 | 268.65 | +3.6% |
| BDX | 2026-11-20 | 1 | 213.26 | 215.44 | +1.0% |
| SWK | 2026-11-20 | 1 | 107.82 | 110.74 | +2.7% |
| REGN | 2026-11-23 | 1 | 923.18 | 942.24 | +2.1% |

Closed trades: 2, longest losing streak 2.

## v0m — v0 that skips buys after an extreme run-up (6-month momentum above +200%). Owner's idea (2026-11-10, MRNA at +425%): in development 6.5% vs 5.6% CAGR and validation 6.8% vs 5.6%, same max DD; a cap on distance above the 200-MA instead LOST return. Paper-traded only.

**Orders for the next open:** BUY ALLE, BUY LH

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| CRL | 2026-11-11 | 4 | 347.38 | 338.26 | -2.6% |
| BBY | 2026-11-11 | 19 | 103.12 | 97.0 | -5.9% |
| CDW | 2026-11-11 | 10 | 171.86 | 170.06 | -1.0% |
| CRWD | 2026-11-11 | 5 | 235.35 | 208.97 | -11.2% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1725.52 | -2.1% |
| RVTY | 2026-11-11 | 10 | 161.07 | 151.29 | -6.1% |
| WDAY | 2026-11-11 | 10 | 190.49 | 176.08 | -7.6% |
| DLTR | 2026-11-11 | 13 | 139.88 | 139.1 | -0.6% |
| A | 2026-11-11 | 14 | 178.99 | 176.04 | -1.6% |
| IQV | 2026-11-11 | 8 | 276.89 | 251.92 | -9.0% |
| TMO | 2026-11-11 | 3 | 719.69 | 688.08 | -4.4% |
| MPC | 2026-11-11 | 3 | 394.85 | 357.69 | -9.4% |
| ACN | 2026-11-11 | 7 | 255.18 | 222.29 | -12.9% |
| TECH | 2026-11-11 | 72 | 72.75 | 72.8 | +0.1% |
| VEEV | 2026-11-20 | 7 | 259.25 | 268.65 | +3.6% |
| BDX | 2026-11-20 | 1 | 213.26 | 215.44 | +1.0% |
| SWK | 2026-11-20 | 1 | 107.82 | 110.74 | +2.7% |
| REGN | 2026-11-23 | 1 | 923.18 | 942.24 | +2.1% |

Closed trades: 2, longest losing streak 2.

## v7 — Earnings-led, concentrated: beat streak + SUE + revenue acceleration; buy only stocks in an uptrend that beat last quarter; top 10, checked weekly; sell when a holding drops out of the top 30. Chosen from a 767-config search as the centre of a robust plateau (24 neighbours: dev 7.6-10.0% CAGR, -20% to -26% max DD).

**Orders for the next open:** none

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MET | 2026-11-11 | 31 | 102.44 | 98.72 | -3.6% |
| REGN | 2026-11-11 | 3 | 904.07 | 942.24 | +4.2% |
| EXPD | 2026-11-11 | 16 | 190.25 | 195.53 | +2.8% |
| MPC | 2026-11-11 | 8 | 394.85 | 357.69 | -9.4% |
| XEL | 2026-11-11 | 39 | 80.14 | 80.51 | +0.5% |
| FTV | 2026-11-11 | 47 | 67.79 | 65.73 | -3.0% |
| NTAP | 2026-11-11 | 17 | 183.89 | 171.64 | -6.7% |
| UDR | 2026-11-11 | 87 | 36.16 | 35.68 | -1.3% |
| VEEV | 2026-11-11 | 10 | 309.93 | 268.65 | -13.3% |
| APP | 2026-11-17 | 7 | 412.56 | 373.92 | -9.4% |

Closed trades: 1, longest losing streak 0.

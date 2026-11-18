# Paper trading — v0, v0m, v7 (forward, out-of-sample)

Start 2026-11-10 with $32,000 each; rules frozen; next-open fills; 10 bps/side. Day 6 of paper trading (data to 2026-11-17).

| Account | Days | Value | Return | Max DD | Trades |
|---|---|---|---|---|---|
| v0 | 6 | $30,516 | -4.64% | -4.6% | 0 |
| v0m | 6 | $30,653 | -4.21% | -4.2% | 0 |
| v7 | 6 | $31,582 | -1.31% | -2.5% | 1 |
| BENCH SPY | 6 | $31,234 | -2.30% | -3.5% | 0 |
| BENCH RSP | 6 | $31,231 | -2.31% | -3.1% | 0 |

## v0 — Production Growth Momentum Rider (ROC126 > 25% & close > SMA200; exit close < SMA200), restricted to point-in-time S&P 500 members; 20 positions, 1% risk.

**Orders for the next open:** BUY REGN, BUY SWK, BUY ALLE

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MRNA | 2026-11-11 | 3 | 252.78 | 206.8 | -18.2% |
| CRL | 2026-11-11 | 4 | 347.38 | 332.16 | -4.4% |
| VEEV | 2026-11-11 | 8 | 309.93 | 288.41 | -6.9% |
| BBY | 2026-11-11 | 19 | 103.12 | 98.4 | -4.6% |
| CDW | 2026-11-11 | 10 | 171.86 | 163.07 | -5.1% |
| CRWD | 2026-11-11 | 5 | 235.35 | 219.58 | -6.7% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1712.95 | -2.8% |
| RVTY | 2026-11-11 | 10 | 161.07 | 147.79 | -8.2% |
| HPE | 2026-11-11 | 20 | 50.9 | 46.09 | -9.4% |
| WDAY | 2026-11-11 | 10 | 190.49 | 182.8 | -4.0% |
| DLTR | 2026-11-11 | 13 | 139.88 | 139.71 | -0.1% |
| A | 2026-11-11 | 14 | 178.99 | 172.22 | -3.8% |
| IQV | 2026-11-11 | 8 | 276.89 | 257.6 | -7.0% |
| TMO | 2026-11-11 | 3 | 719.69 | 686.79 | -4.6% |
| MPC | 2026-11-11 | 3 | 395.95 | 395.61 | -0.1% |
| ACN | 2026-11-11 | 7 | 255.18 | 239.28 | -6.2% |
| TECH | 2026-11-11 | 62 | 72.75 | 72.63 | -0.2% |

Closed trades: 0, longest losing streak 0.

## v0m — v0 that skips buys after an extreme run-up (6-month momentum above +200%). Owner's idea (2026-11-10, MRNA at +425%): in development 6.5% vs 5.6% CAGR and validation 6.8% vs 5.6%, same max DD; a cap on distance above the 200-MA instead LOST return. Paper-traded only.

**Orders for the next open:** BUY REGN, BUY SWK, BUY ALLE, BUY BDX

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| CRL | 2026-11-11 | 4 | 347.38 | 332.16 | -4.4% |
| VEEV | 2026-11-11 | 8 | 309.93 | 288.41 | -6.9% |
| BBY | 2026-11-11 | 19 | 103.12 | 98.4 | -4.6% |
| CDW | 2026-11-11 | 10 | 171.86 | 163.07 | -5.1% |
| CRWD | 2026-11-11 | 5 | 235.35 | 219.58 | -6.7% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1712.95 | -2.8% |
| RVTY | 2026-11-11 | 10 | 161.07 | 147.79 | -8.2% |
| HPE | 2026-11-11 | 20 | 50.9 | 46.09 | -9.4% |
| WDAY | 2026-11-11 | 10 | 190.49 | 182.8 | -4.0% |
| DLTR | 2026-11-11 | 13 | 139.88 | 139.71 | -0.1% |
| A | 2026-11-11 | 14 | 178.99 | 172.22 | -3.8% |
| IQV | 2026-11-11 | 8 | 276.89 | 257.6 | -7.0% |
| TMO | 2026-11-11 | 3 | 719.69 | 686.79 | -4.6% |
| MPC | 2026-11-11 | 3 | 395.95 | 395.61 | -0.1% |
| ACN | 2026-11-11 | 7 | 255.18 | 239.28 | -6.2% |
| TECH | 2026-11-11 | 72 | 72.75 | 72.63 | -0.2% |

Closed trades: 0, longest losing streak 0.

## v7 — Earnings-led, concentrated: beat streak + SUE + revenue acceleration; buy only stocks in an uptrend that beat last quarter; top 10, checked weekly; sell when a holding drops out of the top 30. Chosen from a 767-config search as the centre of a robust plateau (24 neighbours: dev 7.6-10.0% CAGR, -20% to -26% max DD).

**Orders for the next open:** none

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MET | 2026-11-11 | 31 | 102.44 | 101.5 | -0.9% |
| REGN | 2026-11-11 | 3 | 904.99 | 957.76 | +5.8% |
| EXPD | 2026-11-11 | 16 | 190.25 | 190.77 | +0.3% |
| MPC | 2026-11-11 | 8 | 395.95 | 395.61 | -0.1% |
| XEL | 2026-11-11 | 39 | 80.14 | 80.72 | +0.7% |
| FTV | 2026-11-11 | 47 | 67.79 | 66.07 | -2.5% |
| NTAP | 2026-11-11 | 17 | 183.89 | 173.04 | -5.9% |
| UDR | 2026-11-11 | 87 | 36.16 | 36.07 | -0.2% |
| VEEV | 2026-11-11 | 10 | 309.93 | 288.41 | -6.9% |
| APP | 2026-11-17 | 7 | 412.56 | 398.94 | -3.3% |

Closed trades: 1, longest losing streak 0.

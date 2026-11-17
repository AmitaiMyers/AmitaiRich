# Paper trading — v0, v0m, v7 (forward, out-of-sample)

Start 2026-11-10 with $32,000 each; rules frozen; next-open fills; 10 bps/side. Day 5 of paper trading (data to 2026-11-16).

| Account | Days | Value | Return | Max DD | Trades |
|---|---|---|---|---|---|
| v0 | 5 | $31,085 | -2.86% | -2.9% | 0 |
| v0m | 5 | $31,198 | -2.51% | -2.5% | 0 |
| v7 | 5 | $32,093 | +0.29% | -0.9% | 1 |
| BENCH SPY | 5 | $31,550 | -1.31% | -2.6% | 0 |
| BENCH RSP | 5 | $31,687 | -0.88% | -1.7% | 0 |

## v0 — Production Growth Momentum Rider (ROC126 > 25% & close > SMA200; exit close < SMA200), restricted to point-in-time S&P 500 members; 20 positions, 1% risk.

**Orders for the next open:** BUY BDX, BUY SWK, BUY REGN

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MRNA | 2026-11-11 | 3 | 252.78 | 215.27 | -14.8% |
| CRL | 2026-11-11 | 4 | 347.38 | 335.52 | -3.4% |
| VEEV | 2026-11-11 | 8 | 309.93 | 299.28 | -3.4% |
| BBY | 2026-11-11 | 19 | 103.12 | 103.35 | +0.2% |
| CDW | 2026-11-11 | 10 | 171.86 | 165.82 | -3.5% |
| CRWD | 2026-11-11 | 5 | 235.35 | 223.21 | -5.2% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1727.26 | -2.0% |
| RVTY | 2026-11-11 | 10 | 161.07 | 148.85 | -7.6% |
| HPE | 2026-11-11 | 20 | 50.9 | 46.57 | -8.5% |
| WDAY | 2026-11-11 | 10 | 190.49 | 194.06 | +1.9% |
| DLTR | 2026-11-11 | 13 | 139.88 | 138.7 | -0.8% |
| A | 2026-11-11 | 14 | 178.99 | 172.92 | -3.4% |
| IQV | 2026-11-11 | 8 | 276.89 | 264.73 | -4.4% |
| TMO | 2026-11-11 | 3 | 719.69 | 691.33 | -3.9% |
| MPC | 2026-11-11 | 3 | 395.95 | 402.19 | +1.6% |
| ACN | 2026-11-11 | 7 | 255.18 | 247.7 | -2.9% |
| TECH | 2026-11-11 | 62 | 72.75 | 72.79 | +0.1% |

Closed trades: 0, longest losing streak 0.

## v0m — v0 that skips buys after an extreme run-up (6-month momentum above +200%). Owner's idea (2026-11-10, MRNA at +425%): in development 6.5% vs 5.6% CAGR and validation 6.8% vs 5.6%, same max DD; a cap on distance above the 200-MA instead LOST return. Paper-traded only.

**Orders for the next open:** BUY BDX, BUY SWK, BUY REGN, BUY HUM

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| CRL | 2026-11-11 | 4 | 347.38 | 335.52 | -3.4% |
| VEEV | 2026-11-11 | 8 | 309.93 | 299.28 | -3.4% |
| BBY | 2026-11-11 | 19 | 103.12 | 103.35 | +0.2% |
| CDW | 2026-11-11 | 10 | 171.86 | 165.82 | -3.5% |
| CRWD | 2026-11-11 | 5 | 235.35 | 223.21 | -5.2% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1727.26 | -2.0% |
| RVTY | 2026-11-11 | 10 | 161.07 | 148.85 | -7.6% |
| HPE | 2026-11-11 | 20 | 50.9 | 46.57 | -8.5% |
| WDAY | 2026-11-11 | 10 | 190.49 | 194.06 | +1.9% |
| DLTR | 2026-11-11 | 13 | 139.88 | 138.7 | -0.8% |
| A | 2026-11-11 | 14 | 178.99 | 172.92 | -3.4% |
| IQV | 2026-11-11 | 8 | 276.89 | 264.73 | -4.4% |
| TMO | 2026-11-11 | 3 | 719.69 | 691.33 | -3.9% |
| MPC | 2026-11-11 | 3 | 395.95 | 402.19 | +1.6% |
| ACN | 2026-11-11 | 7 | 255.18 | 247.7 | -2.9% |
| TECH | 2026-11-11 | 72 | 72.75 | 72.79 | +0.1% |

Closed trades: 0, longest losing streak 0.

## v7 — Earnings-led, concentrated: beat streak + SUE + revenue acceleration; buy only stocks in an uptrend that beat last quarter; top 10, checked weekly; sell when a holding drops out of the top 30. Chosen from a 767-config search as the centre of a robust plateau (24 neighbours: dev 7.6-10.0% CAGR, -20% to -26% max DD).

**Orders for the next open:** BUY APP

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MET | 2026-11-11 | 31 | 102.44 | 101.45 | -1.0% |
| REGN | 2026-11-11 | 3 | 904.99 | 952.4 | +5.2% |
| EXPD | 2026-11-11 | 16 | 190.25 | 195.34 | +2.7% |
| MPC | 2026-11-11 | 8 | 395.95 | 402.19 | +1.6% |
| XEL | 2026-11-11 | 39 | 80.14 | 81.21 | +1.3% |
| FTV | 2026-11-11 | 47 | 67.79 | 67.53 | -0.4% |
| NTAP | 2026-11-11 | 17 | 183.89 | 177.85 | -3.3% |
| UDR | 2026-11-11 | 87 | 36.16 | 36.37 | +0.6% |
| VEEV | 2026-11-11 | 10 | 309.93 | 299.28 | -3.4% |

Closed trades: 1, longest losing streak 0.

# Paper trading — v0, v0m, v7 (forward, out-of-sample)

Start 2026-11-10 with $32,000 each; rules frozen; next-open fills; 10 bps/side. Day 2 of paper trading (data to 2026-11-11).

| Account | Days | Value | Return | Max DD | Trades |
|---|---|---|---|---|---|
| v0 | 2 | $31,862 | -0.43% | -0.4% | 0 |
| v0m | 2 | $31,874 | -0.39% | -0.4% | 0 |
| v7 | 2 | $32,320 | +1.00% | 0.0% | 0 |
| BENCH SPY | 2 | $32,384 | +1.30% | 0.0% | 0 |
| BENCH RSP | 2 | $32,223 | +0.80% | 0.0% | 0 |

## v0 — Production Growth Momentum Rider (ROC126 > 25% & close > SMA200; exit close < SMA200), restricted to point-in-time S&P 500 members; 20 positions, 1% risk.

**Orders for the next open:** BUY FDS, BUY NTAP, BUY DELL

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MRNA | 2026-11-11 | 3 | 252.78 | 248.69 | -1.6% |
| CRL | 2026-11-11 | 4 | 347.38 | 342.69 | -1.4% |
| VEEV | 2026-11-11 | 8 | 309.93 | 304.77 | -1.7% |
| BBY | 2026-11-11 | 19 | 103.12 | 105.16 | +2.0% |
| CDW | 2026-11-11 | 10 | 171.86 | 173.08 | +0.7% |
| CRWD | 2026-11-11 | 5 | 235.35 | 229.06 | -2.7% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1749.01 | -0.7% |
| RVTY | 2026-11-11 | 10 | 161.07 | 158.25 | -1.8% |
| HPE | 2026-11-11 | 20 | 50.9 | 50.25 | -1.3% |
| WDAY | 2026-11-11 | 10 | 190.49 | 191.16 | +0.4% |
| DLTR | 2026-11-11 | 13 | 139.88 | 142.9 | +2.2% |
| A | 2026-11-11 | 14 | 178.99 | 176.95 | -1.1% |
| IQV | 2026-11-11 | 8 | 276.89 | 274.53 | -0.9% |
| TMO | 2026-11-11 | 3 | 719.69 | 717.71 | -0.3% |
| MPC | 2026-11-11 | 3 | 395.95 | 402.84 | +1.7% |
| ACN | 2026-11-11 | 7 | 255.18 | 253.66 | -0.6% |
| TECH | 2026-11-11 | 62 | 72.83 | 72.8 | -0.0% |

Closed trades: 0, longest losing streak 0.

## v0m — v0 that skips buys after an extreme run-up (6-month momentum above +200%). Owner's idea (2026-11-10, MRNA at +425%): in development 6.5% vs 5.6% CAGR and validation 6.8% vs 5.6%, same max DD; a cap on distance above the 200-MA instead LOST return. Paper-traded only.

**Orders for the next open:** BUY FDS, BUY NTAP, BUY DELL, BUY WSM

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| CRL | 2026-11-11 | 4 | 347.38 | 342.69 | -1.4% |
| VEEV | 2026-11-11 | 8 | 309.93 | 304.77 | -1.7% |
| BBY | 2026-11-11 | 19 | 103.12 | 105.16 | +2.0% |
| CDW | 2026-11-11 | 10 | 171.86 | 173.08 | +0.7% |
| CRWD | 2026-11-11 | 5 | 235.35 | 229.06 | -2.7% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1749.01 | -0.7% |
| RVTY | 2026-11-11 | 10 | 161.07 | 158.25 | -1.8% |
| HPE | 2026-11-11 | 20 | 50.9 | 50.25 | -1.3% |
| WDAY | 2026-11-11 | 10 | 190.49 | 191.16 | +0.4% |
| DLTR | 2026-11-11 | 13 | 139.88 | 142.9 | +2.2% |
| A | 2026-11-11 | 14 | 178.99 | 176.95 | -1.1% |
| IQV | 2026-11-11 | 8 | 276.89 | 274.53 | -0.9% |
| TMO | 2026-11-11 | 3 | 719.69 | 717.71 | -0.3% |
| MPC | 2026-11-11 | 3 | 395.95 | 402.84 | +1.7% |
| ACN | 2026-11-11 | 7 | 255.18 | 253.66 | -0.6% |
| TECH | 2026-11-11 | 72 | 72.83 | 72.8 | -0.0% |

Closed trades: 0, longest losing streak 0.

## v7 — Earnings-led, concentrated: beat streak + SUE + revenue acceleration; buy only stocks in an uptrend that beat last quarter; top 10, checked weekly; sell when a holding drops out of the top 30. Chosen from a 767-config search as the centre of a robust plateau (24 neighbours: dev 7.6-10.0% CAGR, -20% to -26% max DD).

**Orders for the next open:** SELL OXY

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MET | 2026-11-11 | 31 | 102.44 | 102.94 | +0.5% |
| REGN | 2026-11-11 | 3 | 904.99 | 959.41 | +6.0% |
| EXPD | 2026-11-11 | 16 | 190.25 | 194.59 | +2.3% |
| MPC | 2026-11-11 | 8 | 395.95 | 402.84 | +1.7% |
| XEL | 2026-11-11 | 39 | 80.14 | 81.1 | +1.2% |
| FTV | 2026-11-11 | 47 | 67.79 | 67.89 | +0.1% |
| NTAP | 2026-11-11 | 17 | 183.89 | 183.12 | -0.4% |
| UDR | 2026-11-11 | 87 | 36.3 | 36.56 | +0.7% |
| OXY | 2026-11-11 | 55 | 57.26 | 57.24 | -0.0% |
| FRT | 2026-11-11 | 28 | 113.2 | 113.1 | -0.1% |

Closed trades: 0, longest losing streak 0.

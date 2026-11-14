# Paper trading — v0, v0m, v7 (forward, out-of-sample)

Start 2026-11-10 with $32,000 each; rules frozen; next-open fills; 10 bps/side. Day 4 of paper trading (data to 2026-11-13).

| Account | Days | Value | Return | Max DD | Trades |
|---|---|---|---|---|---|
| v0 | 4 | $31,468 | -1.66% | -1.7% | 7 |
| v0m | 4 | $31,536 | -1.45% | -1.5% | 6 |
| v7 | 4 | $32,450 | +1.41% | 0.0% | 1 |
| BENCH SPY | 4 | $32,155 | +0.58% | -0.7% | 0 |
| BENCH RSP | 4 | $32,009 | +0.13% | -0.9% | 0 |

## v0 — Production Growth Momentum Rider (ROC126 > 25% & close > SMA200; exit close < SMA200), restricted to point-in-time S&P 500 members; 20 positions, 1% risk.

**Orders for the next open:** BUY BDX, BUY SWK, BUY VLO, BUY WSM, BUY ROP, BUY BAX, BUY LH, BUY HUM

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| CRL | 2026-11-11 | 4 | 347.38 | 337.97 | -2.7% |
| BBY | 2026-11-11 | 19 | 103.12 | 104.07 | +0.9% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1738.91 | -1.3% |
| RVTY | 2026-11-11 | 10 | 161.07 | 154.39 | -4.1% |
| DLTR | 2026-11-11 | 13 | 139.88 | 138.08 | -1.3% |
| A | 2026-11-11 | 14 | 178.99 | 173.96 | -2.8% |
| TMO | 2026-11-11 | 3 | 719.69 | 700.22 | -2.7% |
| MPC | 2026-11-11 | 3 | 395.95 | 414.65 | +4.7% |
| ACN | 2026-11-11 | 7 | 255.18 | 250.49 | -1.8% |
| TECH | 2026-11-11 | 62 | 72.75 | 72.8 | +0.1% |
| FDS | 2026-11-13 | 6 | 334.84 | 332.69 | -0.6% |
| NTAP | 2026-11-13 | 7 | 186.51 | 181.37 | -2.8% |

Closed trades: 7, longest losing streak 4.

## v0m — v0 that skips buys after an extreme run-up (6-month momentum above +200%). Owner's idea (2026-11-10, MRNA at +425%): in development 6.5% vs 5.6% CAGR and validation 6.8% vs 5.6%, same max DD; a cap on distance above the 200-MA instead LOST return. Paper-traded only.

**Orders for the next open:** BUY BDX, BUY SWK, BUY WSM, BUY ROP, BUY BAX, BUY LH, BUY HUM

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| CRL | 2026-11-11 | 4 | 347.38 | 337.97 | -2.7% |
| BBY | 2026-11-11 | 19 | 103.12 | 104.07 | +0.9% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1738.91 | -1.3% |
| RVTY | 2026-11-11 | 10 | 161.07 | 154.39 | -4.1% |
| DLTR | 2026-11-11 | 13 | 139.88 | 138.08 | -1.3% |
| A | 2026-11-11 | 14 | 178.99 | 173.96 | -2.8% |
| TMO | 2026-11-11 | 3 | 719.69 | 700.22 | -2.7% |
| MPC | 2026-11-11 | 3 | 395.95 | 414.65 | +4.7% |
| ACN | 2026-11-11 | 7 | 255.18 | 250.49 | -1.8% |
| TECH | 2026-11-11 | 72 | 72.75 | 72.8 | +0.1% |
| FDS | 2026-11-13 | 6 | 334.84 | 332.69 | -0.6% |
| NTAP | 2026-11-13 | 7 | 186.51 | 181.37 | -2.8% |
| VLO | 2026-11-13 | 4 | 378.75 | 379.83 | +0.3% |

Closed trades: 6, longest losing streak 4.

## v7 — Earnings-led, concentrated: beat streak + SUE + revenue acceleration; buy only stocks in an uptrend that beat last quarter; top 10, checked weekly; sell when a holding drops out of the top 30. Chosen from a 767-config search as the centre of a robust plateau (24 neighbours: dev 7.6-10.0% CAGR, -20% to -26% max DD).

**Orders for the next open:** SELL OXY, BUY MU

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MET | 2026-11-11 | 31 | 102.44 | 102.65 | +0.2% |
| REGN | 2026-11-11 | 3 | 904.99 | 955.47 | +5.6% |
| EXPD | 2026-11-11 | 16 | 190.25 | 194.8 | +2.4% |
| MPC | 2026-11-11 | 8 | 395.95 | 414.65 | +4.7% |
| XEL | 2026-11-11 | 39 | 80.14 | 81.61 | +1.8% |
| NTAP | 2026-11-11 | 17 | 183.89 | 181.37 | -1.4% |
| UDR | 2026-11-11 | 87 | 36.3 | 36.44 | +0.4% |
| OXY | 2026-11-11 | 55 | 57.26 | 58.75 | +2.6% |
| FRT | 2026-11-11 | 28 | 113.2 | 112.92 | -0.2% |

Closed trades: 1, longest losing streak 1.

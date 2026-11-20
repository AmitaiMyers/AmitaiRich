# Paper trading — v0, v0m, v7 (forward, out-of-sample)

Start 2026-11-10 with $32,000 each; rules frozen; next-open fills; 10 bps/side. Day 8 of paper trading (data to 2026-11-19).

| Account | Days | Value | Return | Max DD | Trades |
|---|---|---|---|---|---|
| v0 | 8 | $30,218 | -5.57% | -5.6% | 7 |
| v0m | 8 | $30,386 | -5.04% | -5.0% | 6 |
| v7 | 8 | $30,875 | -3.51% | -4.6% | 4 |
| BENCH SPY | 8 | $30,538 | -4.47% | -5.7% | 0 |
| BENCH RSP | 8 | $30,636 | -4.17% | -4.9% | 0 |

## v0 — Production Growth Momentum Rider (ROC126 > 25% & close > SMA200; exit close < SMA200), restricted to point-in-time S&P 500 members; 20 positions, 1% risk.

**Orders for the next open:** BUY LH, BUY REGN, BUY VLO, BUY MCK, BUY ADP, BUY FDS, BUY NTAP

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| CRL | 2026-11-11 | 4 | 347.38 | 327.93 | -5.6% |
| BBY | 2026-11-11 | 19 | 103.12 | 99.27 | -3.7% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1705.66 | -3.2% |
| RVTY | 2026-11-11 | 10 | 161.07 | 151.59 | -5.9% |
| DLTR | 2026-11-11 | 13 | 139.88 | 140.24 | +0.3% |
| A | 2026-11-11 | 14 | 178.99 | 175.34 | -2.0% |
| TMO | 2026-11-11 | 3 | 719.69 | 688.75 | -4.3% |
| MPC | 2026-11-11 | 3 | 394.85 | 367.93 | -6.8% |
| ACN | 2026-11-11 | 7 | 255.18 | 218.58 | -14.3% |
| TECH | 2026-11-11 | 62 | 72.75 | 72.7 | -0.1% |
| SWK | 2026-11-19 | 17 | 110.37 | 107.64 | -2.5% |
| BDX | 2026-11-19 | 14 | 215.23 | 212.68 | -1.2% |
| ROP | 2026-11-19 | 4 | 471.6 | 462.96 | -1.8% |

Closed trades: 7, longest losing streak 3.

## v0m — v0 that skips buys after an extreme run-up (6-month momentum above +200%). Owner's idea (2026-11-10, MRNA at +425%): in development 6.5% vs 5.6% CAGR and validation 6.8% vs 5.6%, same max DD; a cap on distance above the 200-MA instead LOST return. Paper-traded only.

**Orders for the next open:** BUY LH, BUY REGN, BUY VLO, BUY MCK, BUY ADP, BUY FDS, BUY NTAP

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| CRL | 2026-11-11 | 4 | 347.38 | 327.93 | -5.6% |
| BBY | 2026-11-11 | 19 | 103.12 | 99.27 | -3.7% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1705.66 | -3.2% |
| RVTY | 2026-11-11 | 10 | 161.07 | 151.59 | -5.9% |
| DLTR | 2026-11-11 | 13 | 139.88 | 140.24 | +0.3% |
| A | 2026-11-11 | 14 | 178.99 | 175.34 | -2.0% |
| TMO | 2026-11-11 | 3 | 719.69 | 688.75 | -4.3% |
| MPC | 2026-11-11 | 3 | 394.85 | 367.93 | -6.8% |
| ACN | 2026-11-11 | 7 | 255.18 | 218.58 | -14.3% |
| TECH | 2026-11-11 | 72 | 72.75 | 72.7 | -0.1% |
| SWK | 2026-11-19 | 17 | 110.37 | 107.64 | -2.5% |
| BDX | 2026-11-19 | 14 | 215.23 | 212.68 | -1.2% |
| ROP | 2026-11-19 | 4 | 471.6 | 462.96 | -1.8% |

Closed trades: 6, longest losing streak 3.

## v7 — Earnings-led, concentrated: beat streak + SUE + revenue acceleration; buy only stocks in an uptrend that beat last quarter; top 10, checked weekly; sell when a holding drops out of the top 30. Chosen from a 767-config search as the centre of a robust plateau (24 neighbours: dev 7.6-10.0% CAGR, -20% to -26% max DD).

**Orders for the next open:** BUY ADI, BUY MDT, BUY TRGP

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MET | 2026-11-11 | 31 | 102.44 | 97.6 | -4.7% |
| REGN | 2026-11-11 | 3 | 904.99 | 923.34 | +2.0% |
| EXPD | 2026-11-11 | 16 | 190.25 | 193.14 | +1.5% |
| MPC | 2026-11-11 | 8 | 394.85 | 367.93 | -6.8% |
| XEL | 2026-11-11 | 39 | 80.14 | 79.46 | -0.8% |
| NTAP | 2026-11-11 | 17 | 183.89 | 170.18 | -7.5% |
| UDR | 2026-11-11 | 87 | 36.16 | 35.33 | -2.3% |

Closed trades: 4, longest losing streak 3.

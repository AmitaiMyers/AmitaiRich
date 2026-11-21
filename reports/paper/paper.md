# Paper trading — v0, v0m, v7 (forward, out-of-sample)

Start 2026-11-10 with $32,000 each; rules frozen; next-open fills; 10 bps/side. Day 9 of paper trading (data to 2026-11-20).

| Account | Days | Value | Return | Max DD | Trades |
|---|---|---|---|---|---|
| v0 | 9 | $29,689 | -7.22% | -7.2% | 1 |
| v0m | 9 | $29,861 | -6.68% | -6.7% | 1 |
| v7 | 9 | $30,066 | -6.04% | -7.1% | 1 |
| BENCH SPY | 9 | $29,444 | -7.90% | -9.1% | 0 |
| BENCH RSP | 9 | $30,033 | -6.05% | -6.8% | 0 |

## v0 — Production Growth Momentum Rider (ROC126 > 25% & close > SMA200; exit close < SMA200), restricted to point-in-time S&P 500 members; 20 positions, 1% risk.

**Orders for the next open:** SELL HPE, BUY REGN

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MRNA | 2026-11-11 | 3 | 252.78 | 195.0 | -22.9% |
| CRL | 2026-11-11 | 4 | 347.38 | 314.32 | -9.5% |
| BBY | 2026-11-11 | 19 | 103.12 | 97.95 | -5.0% |
| CDW | 2026-11-11 | 10 | 171.86 | 161.78 | -5.9% |
| CRWD | 2026-11-11 | 5 | 235.35 | 229.44 | -2.5% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1666.88 | -5.4% |
| RVTY | 2026-11-11 | 10 | 161.07 | 145.22 | -9.8% |
| HPE | 2026-11-11 | 20 | 50.9 | 40.91 | -19.6% |
| WDAY | 2026-11-11 | 10 | 190.49 | 174.52 | -8.4% |
| DLTR | 2026-11-11 | 13 | 139.88 | 137.96 | -1.4% |
| A | 2026-11-11 | 14 | 178.99 | 170.38 | -4.8% |
| IQV | 2026-11-11 | 8 | 276.89 | 245.82 | -11.2% |
| TMO | 2026-11-11 | 3 | 719.69 | 669.54 | -7.0% |
| MPC | 2026-11-11 | 3 | 394.85 | 367.19 | -7.0% |
| ACN | 2026-11-11 | 7 | 255.18 | 221.17 | -13.3% |
| TECH | 2026-11-11 | 62 | 72.75 | 72.67 | -0.1% |
| VEEV | 2026-11-20 | 7 | 259.25 | 266.22 | +2.7% |
| BDX | 2026-11-20 | 1 | 213.26 | 212.78 | -0.2% |
| SWK | 2026-11-20 | 1 | 107.82 | 106.62 | -1.1% |

Closed trades: 1, longest losing streak 1.

## v0m — v0 that skips buys after an extreme run-up (6-month momentum above +200%). Owner's idea (2026-11-10, MRNA at +425%): in development 6.5% vs 5.6% CAGR and validation 6.8% vs 5.6%, same max DD; a cap on distance above the 200-MA instead LOST return. Paper-traded only.

**Orders for the next open:** SELL HPE, BUY REGN, BUY LH

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| CRL | 2026-11-11 | 4 | 347.38 | 314.32 | -9.5% |
| BBY | 2026-11-11 | 19 | 103.12 | 97.95 | -5.0% |
| CDW | 2026-11-11 | 10 | 171.86 | 161.78 | -5.9% |
| CRWD | 2026-11-11 | 5 | 235.35 | 229.44 | -2.5% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1666.88 | -5.4% |
| RVTY | 2026-11-11 | 10 | 161.07 | 145.22 | -9.8% |
| HPE | 2026-11-11 | 20 | 50.9 | 40.91 | -19.6% |
| WDAY | 2026-11-11 | 10 | 190.49 | 174.52 | -8.4% |
| DLTR | 2026-11-11 | 13 | 139.88 | 137.96 | -1.4% |
| A | 2026-11-11 | 14 | 178.99 | 170.38 | -4.8% |
| IQV | 2026-11-11 | 8 | 276.89 | 245.82 | -11.2% |
| TMO | 2026-11-11 | 3 | 719.69 | 669.54 | -7.0% |
| MPC | 2026-11-11 | 3 | 394.85 | 367.19 | -7.0% |
| ACN | 2026-11-11 | 7 | 255.18 | 221.17 | -13.3% |
| TECH | 2026-11-11 | 72 | 72.75 | 72.67 | -0.1% |
| VEEV | 2026-11-20 | 7 | 259.25 | 266.22 | +2.7% |
| BDX | 2026-11-20 | 1 | 213.26 | 212.78 | -0.2% |
| SWK | 2026-11-20 | 1 | 107.82 | 106.62 | -1.1% |

Closed trades: 1, longest losing streak 1.

## v7 — Earnings-led, concentrated: beat streak + SUE + revenue acceleration; buy only stocks in an uptrend that beat last quarter; top 10, checked weekly; sell when a holding drops out of the top 30. Chosen from a 767-config search as the centre of a robust plateau (24 neighbours: dev 7.6-10.0% CAGR, -20% to -26% max DD).

**Orders for the next open:** none

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MET | 2026-11-11 | 31 | 102.44 | 95.67 | -6.6% |
| REGN | 2026-11-11 | 3 | 904.07 | 920.69 | +1.8% |
| EXPD | 2026-11-11 | 16 | 190.25 | 192.56 | +1.2% |
| MPC | 2026-11-11 | 8 | 394.85 | 367.19 | -7.0% |
| XEL | 2026-11-11 | 39 | 80.14 | 79.3 | -1.0% |
| FTV | 2026-11-11 | 47 | 67.79 | 64.16 | -5.4% |
| NTAP | 2026-11-11 | 17 | 183.89 | 157.65 | -14.3% |
| UDR | 2026-11-11 | 87 | 36.16 | 35.45 | -2.0% |
| VEEV | 2026-11-11 | 10 | 309.93 | 266.22 | -14.1% |
| APP | 2026-11-17 | 7 | 412.56 | 348.29 | -15.6% |

Closed trades: 1, longest losing streak 0.

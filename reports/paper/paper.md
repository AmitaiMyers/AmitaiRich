# Paper trading — v0, v0m, v7 (forward, out-of-sample)

Start 2026-11-10 with $32,000 each; rules frozen; next-open fills; 10 bps/side. Day 14 of paper trading (data to 2026-11-27).

| Account | Days | Value | Return | Max DD | Trades |
|---|---|---|---|---|---|
| v0 | 14 | $31,059 | -2.94% | -7.2% | 2 |
| v0m | 14 | $31,132 | -2.71% | -6.7% | 2 |
| v7 | 14 | $31,455 | -1.70% | -7.1% | 1 |
| BENCH SPY | 13 | $31,061 | -2.84% | -9.1% | 0 |
| BENCH RSP | 13 | $31,608 | -1.13% | -6.8% | 0 |

## v0 — Production Growth Momentum Rider (ROC126 > 25% & close > SMA200; exit close < SMA200), restricted to point-in-time S&P 500 members; 20 positions, 1% risk.

**Orders for the next open:** none

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MRNA | 2026-11-11 | 3 | 252.78 | 228.64 | -9.5% |
| CRL | 2026-11-11 | 4 | 347.38 | 337.39 | -2.9% |
| BBY | 2026-11-11 | 19 | 103.12 | 104.18 | +1.0% |
| CDW | 2026-11-11 | 10 | 171.15 | 179.1 | +4.6% |
| CRWD | 2026-11-11 | 5 | 235.35 | 217.2 | -7.7% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1680.49 | -4.6% |
| RVTY | 2026-11-11 | 10 | 161.07 | 151.27 | -6.1% |
| WDAY | 2026-11-11 | 10 | 190.49 | 181.93 | -4.5% |
| DLTR | 2026-11-11 | 13 | 139.88 | 148.53 | +6.2% |
| A | 2026-11-11 | 14 | 178.99 | 180.05 | +0.6% |
| IQV | 2026-11-11 | 8 | 276.89 | 249.39 | -9.9% |
| TMO | 2026-11-11 | 3 | 719.69 | 683.04 | -5.1% |
| MPC | 2026-11-11 | 3 | 394.85 | 359.8 | -8.9% |
| ACN | 2026-11-11 | 7 | 255.18 | 241.84 | -5.2% |
| TECH | 2026-11-11 | 62 | 72.75 | 72.82 | +0.1% |
| VEEV | 2026-11-20 | 7 | 259.25 | 271.6 | +4.8% |
| BDX | 2026-11-20 | 1 | 213.26 | 219.36 | +2.9% |
| SWK | 2026-11-20 | 1 | 107.82 | 110.92 | +2.9% |
| REGN | 2026-11-23 | 1 | 923.18 | 992.14 | +7.5% |

Closed trades: 2, longest losing streak 2.

## v0m — v0 that skips buys after an extreme run-up (6-month momentum above +200%). Owner's idea (2026-11-10, MRNA at +425%): in development 6.5% vs 5.6% CAGR and validation 6.8% vs 5.6%, same max DD; a cap on distance above the 200-MA instead LOST return. Paper-traded only.

**Orders for the next open:** none

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| CRL | 2026-11-11 | 4 | 347.38 | 337.39 | -2.9% |
| BBY | 2026-11-11 | 19 | 103.12 | 104.18 | +1.0% |
| CDW | 2026-11-11 | 10 | 171.15 | 179.1 | +4.6% |
| CRWD | 2026-11-11 | 5 | 235.35 | 217.2 | -7.7% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1680.49 | -4.6% |
| RVTY | 2026-11-11 | 10 | 161.07 | 151.27 | -6.1% |
| WDAY | 2026-11-11 | 10 | 190.49 | 181.93 | -4.5% |
| DLTR | 2026-11-11 | 13 | 139.88 | 148.53 | +6.2% |
| A | 2026-11-11 | 14 | 178.99 | 180.05 | +0.6% |
| IQV | 2026-11-11 | 8 | 276.89 | 249.39 | -9.9% |
| TMO | 2026-11-11 | 3 | 719.69 | 683.04 | -5.1% |
| MPC | 2026-11-11 | 3 | 394.85 | 359.8 | -8.9% |
| ACN | 2026-11-11 | 7 | 255.18 | 241.84 | -5.2% |
| TECH | 2026-11-11 | 72 | 72.75 | 72.82 | +0.1% |
| VEEV | 2026-11-20 | 7 | 259.25 | 271.6 | +4.8% |
| BDX | 2026-11-20 | 1 | 213.26 | 219.36 | +2.9% |
| SWK | 2026-11-20 | 1 | 107.82 | 110.92 | +2.9% |
| REGN | 2026-11-23 | 1 | 923.18 | 992.14 | +7.5% |

Closed trades: 2, longest losing streak 2.

## v7 — Earnings-led, concentrated: beat streak + SUE + revenue acceleration; buy only stocks in an uptrend that beat last quarter; top 10, checked weekly; sell when a holding drops out of the top 30. Chosen from a 767-config search as the centre of a robust plateau (24 neighbours: dev 7.6-10.0% CAGR, -20% to -26% max DD).

**Orders for the next open:** SELL APP, SELL EXPD, SELL FTV, SELL MET, SELL MPC, SELL NTAP, SELL REGN, SELL UDR, SELL VEEV, SELL XEL

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MET | 2026-11-11 | 31 | 102.44 | 101.07 | -1.3% |
| REGN | 2026-11-11 | 3 | 904.07 | 992.14 | +9.7% |
| EXPD | 2026-11-11 | 16 | 190.25 | 199.46 | +4.8% |
| MPC | 2026-11-11 | 8 | 394.85 | 359.8 | -8.9% |
| XEL | 2026-11-11 | 39 | 80.14 | 81.47 | +1.7% |
| FTV | 2026-11-11 | 47 | 67.72 | 66.03 | -2.5% |
| NTAP | 2026-11-11 | 17 | 183.89 | 172.67 | -6.1% |
| UDR | 2026-11-11 | 87 | 36.16 | 36.77 | +1.7% |
| VEEV | 2026-11-11 | 10 | 309.93 | 271.6 | -12.4% |
| APP | 2026-11-17 | 7 | 412.56 | 399.21 | -3.2% |

Closed trades: 1, longest losing streak 0.

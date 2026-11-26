# Paper trading — v0, v0m, v7 (forward, out-of-sample)

Start 2026-11-10 with $32,000 each; rules frozen; next-open fills; 10 bps/side. Day 12 of paper trading (data to 2026-11-25).

| Account | Days | Value | Return | Max DD | Trades |
|---|---|---|---|---|---|
| v0 | 12 | $30,846 | -3.61% | -7.2% | 2 |
| v0m | 12 | $30,941 | -3.31% | -6.7% | 2 |
| v7 | 12 | $30,964 | -3.24% | -7.1% | 1 |
| BENCH SPY | 12 | $30,573 | -4.36% | -9.1% | 0 |
| BENCH RSP | 12 | $31,228 | -2.32% | -6.8% | 0 |

## v0 — Production Growth Momentum Rider (ROC126 > 25% & close > SMA200; exit close < SMA200), restricted to point-in-time S&P 500 members; 20 positions, 1% risk.

**Orders for the next open:** BUY ROP

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MRNA | 2026-11-11 | 3 | 252.78 | 220.84 | -12.6% |
| CRL | 2026-11-11 | 4 | 347.38 | 332.08 | -4.4% |
| BBY | 2026-11-11 | 19 | 103.12 | 102.58 | -0.5% |
| CDW | 2026-11-11 | 10 | 171.15 | 174.97 | +2.2% |
| CRWD | 2026-11-11 | 5 | 235.35 | 209.3 | -11.1% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1664.55 | -5.5% |
| RVTY | 2026-11-11 | 10 | 161.07 | 150.82 | -6.4% |
| WDAY | 2026-11-11 | 10 | 190.49 | 180.44 | -5.3% |
| DLTR | 2026-11-11 | 13 | 139.88 | 152.21 | +8.8% |
| A | 2026-11-11 | 14 | 178.99 | 178.44 | -0.3% |
| IQV | 2026-11-11 | 8 | 276.89 | 251.12 | -9.3% |
| TMO | 2026-11-11 | 3 | 719.69 | 685.52 | -4.7% |
| MPC | 2026-11-11 | 3 | 394.85 | 346.27 | -12.3% |
| ACN | 2026-11-11 | 7 | 255.18 | 240.49 | -5.8% |
| TECH | 2026-11-11 | 62 | 72.75 | 72.65 | -0.1% |
| VEEV | 2026-11-20 | 7 | 259.25 | 271.9 | +4.9% |
| BDX | 2026-11-20 | 1 | 213.26 | 221.24 | +3.7% |
| SWK | 2026-11-20 | 1 | 107.82 | 109.22 | +1.3% |
| REGN | 2026-11-23 | 1 | 923.18 | 981.87 | +6.4% |

Closed trades: 2, longest losing streak 2.

## v0m — v0 that skips buys after an extreme run-up (6-month momentum above +200%). Owner's idea (2026-11-10, MRNA at +425%): in development 6.5% vs 5.6% CAGR and validation 6.8% vs 5.6%, same max DD; a cap on distance above the 200-MA instead LOST return. Paper-traded only.

**Orders for the next open:** BUY ROP, BUY ALLE

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| CRL | 2026-11-11 | 4 | 347.38 | 332.08 | -4.4% |
| BBY | 2026-11-11 | 19 | 103.12 | 102.58 | -0.5% |
| CDW | 2026-11-11 | 10 | 171.15 | 174.97 | +2.2% |
| CRWD | 2026-11-11 | 5 | 235.35 | 209.3 | -11.1% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1664.55 | -5.5% |
| RVTY | 2026-11-11 | 10 | 161.07 | 150.82 | -6.4% |
| WDAY | 2026-11-11 | 10 | 190.49 | 180.44 | -5.3% |
| DLTR | 2026-11-11 | 13 | 139.88 | 152.21 | +8.8% |
| A | 2026-11-11 | 14 | 178.99 | 178.44 | -0.3% |
| IQV | 2026-11-11 | 8 | 276.89 | 251.12 | -9.3% |
| TMO | 2026-11-11 | 3 | 719.69 | 685.52 | -4.7% |
| MPC | 2026-11-11 | 3 | 394.85 | 346.27 | -12.3% |
| ACN | 2026-11-11 | 7 | 255.18 | 240.49 | -5.8% |
| TECH | 2026-11-11 | 72 | 72.75 | 72.65 | -0.1% |
| VEEV | 2026-11-20 | 7 | 259.25 | 271.9 | +4.9% |
| BDX | 2026-11-20 | 1 | 213.26 | 221.24 | +3.7% |
| SWK | 2026-11-20 | 1 | 107.82 | 109.22 | +1.3% |
| REGN | 2026-11-23 | 1 | 923.18 | 981.87 | +6.4% |

Closed trades: 2, longest losing streak 2.

## v7 — Earnings-led, concentrated: beat streak + SUE + revenue acceleration; buy only stocks in an uptrend that beat last quarter; top 10, checked weekly; sell when a holding drops out of the top 30. Chosen from a 767-config search as the centre of a robust plateau (24 neighbours: dev 7.6-10.0% CAGR, -20% to -26% max DD).

**Orders for the next open:** none

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MET | 2026-11-11 | 31 | 102.44 | 99.78 | -2.6% |
| REGN | 2026-11-11 | 3 | 904.07 | 981.87 | +8.6% |
| EXPD | 2026-11-11 | 16 | 190.25 | 198.19 | +4.2% |
| MPC | 2026-11-11 | 8 | 394.85 | 346.27 | -12.3% |
| XEL | 2026-11-11 | 39 | 80.14 | 81.11 | +1.2% |
| FTV | 2026-11-11 | 47 | 67.79 | 66.11 | -2.5% |
| NTAP | 2026-11-11 | 17 | 183.89 | 165.0 | -10.3% |
| UDR | 2026-11-11 | 87 | 36.16 | 36.67 | +1.4% |
| VEEV | 2026-11-11 | 10 | 309.93 | 271.9 | -12.3% |
| APP | 2026-11-17 | 7 | 412.56 | 378.95 | -8.1% |

Closed trades: 1, longest losing streak 0.

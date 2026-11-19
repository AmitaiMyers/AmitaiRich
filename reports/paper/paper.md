# Paper trading — v0, v0m, v7 (forward, out-of-sample)

Start 2026-11-10 with $32,000 each; rules frozen; next-open fills; 10 bps/side. Day 7 of paper trading (data to 2026-11-18).

| Account | Days | Value | Return | Max DD | Trades |
|---|---|---|---|---|---|
| v0 | 7 | $30,584 | -4.42% | -4.6% | 0 |
| v0m | 7 | $30,752 | -3.90% | -4.2% | 0 |
| v7 | 7 | $31,143 | -2.68% | -3.8% | 1 |
| BENCH SPY | 7 | $31,140 | -2.59% | -3.8% | 0 |
| BENCH RSP | 7 | $31,183 | -2.45% | -3.2% | 0 |

## v0 — Production Growth Momentum Rider (ROC126 > 25% & close > SMA200; exit close < SMA200), restricted to point-in-time S&P 500 members; 20 positions, 1% risk.

**Orders for the next open:** BUY SWK, BUY BDX, BUY ROP

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MRNA | 2026-11-11 | 3 | 252.78 | 196.79 | -22.1% |
| CRL | 2026-11-11 | 4 | 347.38 | 333.25 | -4.1% |
| VEEV | 2026-11-11 | 8 | 309.93 | 277.2 | -10.6% |
| BBY | 2026-11-11 | 19 | 103.12 | 100.31 | -2.7% |
| CDW | 2026-11-11 | 10 | 171.86 | 169.01 | -1.7% |
| CRWD | 2026-11-11 | 5 | 235.35 | 237.03 | +0.7% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1737.26 | -1.4% |
| RVTY | 2026-11-11 | 10 | 161.07 | 152.43 | -5.4% |
| HPE | 2026-11-11 | 20 | 50.9 | 45.78 | -10.1% |
| WDAY | 2026-11-11 | 10 | 190.49 | 177.45 | -6.8% |
| DLTR | 2026-11-11 | 13 | 139.88 | 142.44 | +1.8% |
| A | 2026-11-11 | 14 | 178.99 | 177.33 | -0.9% |
| IQV | 2026-11-11 | 8 | 276.89 | 257.84 | -6.9% |
| TMO | 2026-11-11 | 3 | 719.69 | 692.74 | -3.7% |
| MPC | 2026-11-11 | 3 | 394.85 | 373.86 | -5.3% |
| ACN | 2026-11-11 | 7 | 255.18 | 227.49 | -10.9% |
| TECH | 2026-11-11 | 62 | 72.75 | 72.75 | -0.0% |

Closed trades: 0, longest losing streak 0.

## v0m — v0 that skips buys after an extreme run-up (6-month momentum above +200%). Owner's idea (2026-11-10, MRNA at +425%): in development 6.5% vs 5.6% CAGR and validation 6.8% vs 5.6%, same max DD; a cap on distance above the 200-MA instead LOST return. Paper-traded only.

**Orders for the next open:** BUY SWK, BUY BDX, BUY ROP, BUY ALLE

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| CRL | 2026-11-11 | 4 | 347.38 | 333.25 | -4.1% |
| VEEV | 2026-11-11 | 8 | 309.93 | 277.2 | -10.6% |
| BBY | 2026-11-11 | 19 | 103.12 | 100.31 | -2.7% |
| CDW | 2026-11-11 | 10 | 171.86 | 169.01 | -1.7% |
| CRWD | 2026-11-11 | 5 | 235.35 | 237.03 | +0.7% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1737.26 | -1.4% |
| RVTY | 2026-11-11 | 10 | 161.07 | 152.43 | -5.4% |
| HPE | 2026-11-11 | 20 | 50.9 | 45.78 | -10.1% |
| WDAY | 2026-11-11 | 10 | 190.49 | 177.45 | -6.8% |
| DLTR | 2026-11-11 | 13 | 139.88 | 142.44 | +1.8% |
| A | 2026-11-11 | 14 | 178.99 | 177.33 | -0.9% |
| IQV | 2026-11-11 | 8 | 276.89 | 257.84 | -6.9% |
| TMO | 2026-11-11 | 3 | 719.69 | 692.74 | -3.7% |
| MPC | 2026-11-11 | 3 | 394.85 | 373.86 | -5.3% |
| ACN | 2026-11-11 | 7 | 255.18 | 227.49 | -10.9% |
| TECH | 2026-11-11 | 72 | 72.75 | 72.75 | -0.0% |

Closed trades: 0, longest losing streak 0.

## v7 — Earnings-led, concentrated: beat streak + SUE + revenue acceleration; buy only stocks in an uptrend that beat last quarter; top 10, checked weekly; sell when a holding drops out of the top 30. Chosen from a 767-config search as the centre of a robust plateau (24 neighbours: dev 7.6-10.0% CAGR, -20% to -26% max DD).

**Orders for the next open:** none

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MET | 2026-11-11 | 31 | 102.44 | 99.79 | -2.6% |
| REGN | 2026-11-11 | 3 | 904.99 | 945.53 | +4.5% |
| EXPD | 2026-11-11 | 16 | 190.25 | 188.88 | -0.7% |
| MPC | 2026-11-11 | 8 | 394.85 | 373.86 | -5.3% |
| XEL | 2026-11-11 | 39 | 80.14 | 80.65 | +0.6% |
| FTV | 2026-11-11 | 47 | 67.79 | 66.73 | -1.6% |
| NTAP | 2026-11-11 | 17 | 183.89 | 172.19 | -6.4% |
| UDR | 2026-11-11 | 87 | 36.16 | 36.08 | -0.2% |
| VEEV | 2026-11-11 | 10 | 309.93 | 277.2 | -10.6% |
| APP | 2026-11-17 | 7 | 412.56 | 390.91 | -5.2% |

Closed trades: 1, longest losing streak 0.

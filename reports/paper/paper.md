# Paper trading — v0, v0m, v7 (forward, out-of-sample)

Start 2026-11-10 with $32,000 each; rules frozen; next-open fills; 10 bps/side. Day 3 of paper trading (data to 2026-11-12).

| Account | Days | Value | Return | Max DD | Trades |
|---|---|---|---|---|---|
| v0 | 3 | $31,562 | -1.37% | -1.4% | 0 |
| v0m | 3 | $31,627 | -1.17% | -1.2% | 0 |
| v7 | 3 | $32,434 | +1.36% | 0.0% | 0 |
| BENCH SPY | 3 | $32,271 | +0.95% | -0.3% | 0 |
| BENCH RSP | 3 | $31,945 | -0.07% | -0.9% | 0 |

## v0 — Production Growth Momentum Rider (ROC126 > 25% & close > SMA200; exit close < SMA200), restricted to point-in-time S&P 500 members; 20 positions, 1% risk.

**Orders for the next open:** BUY FDS, BUY NTAP, BUY PSX

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MRNA | 2026-11-11 | 3 | 252.78 | 231.35 | -8.5% |
| CRL | 2026-11-11 | 4 | 347.38 | 340.81 | -1.9% |
| VEEV | 2026-11-11 | 8 | 309.93 | 302.42 | -2.4% |
| BBY | 2026-11-11 | 19 | 103.12 | 103.41 | +0.3% |
| CDW | 2026-11-11 | 10 | 171.86 | 172.79 | +0.5% |
| CRWD | 2026-11-11 | 5 | 235.35 | 229.87 | -2.3% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1730.93 | -1.8% |
| RVTY | 2026-11-11 | 10 | 161.07 | 157.02 | -2.5% |
| HPE | 2026-11-11 | 20 | 50.9 | 50.16 | -1.5% |
| WDAY | 2026-11-11 | 10 | 190.49 | 190.64 | +0.1% |
| DLTR | 2026-11-11 | 13 | 139.88 | 141.27 | +1.0% |
| A | 2026-11-11 | 14 | 178.99 | 173.01 | -3.3% |
| IQV | 2026-11-11 | 8 | 276.89 | 271.11 | -2.1% |
| TMO | 2026-11-11 | 3 | 719.69 | 699.44 | -2.8% |
| MPC | 2026-11-11 | 3 | 395.95 | 412.85 | +4.3% |
| ACN | 2026-11-11 | 7 | 255.18 | 249.95 | -2.0% |
| TECH | 2026-11-11 | 62 | 72.83 | 72.84 | +0.0% |

Closed trades: 0, longest losing streak 0.

## v0m — v0 that skips buys after an extreme run-up (6-month momentum above +200%). Owner's idea (2026-11-10, MRNA at +425%): in development 6.5% vs 5.6% CAGR and validation 6.8% vs 5.6%, same max DD; a cap on distance above the 200-MA instead LOST return. Paper-traded only.

**Orders for the next open:** BUY FDS, BUY NTAP, BUY PSX, BUY VLO

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| CRL | 2026-11-11 | 4 | 347.38 | 340.81 | -1.9% |
| VEEV | 2026-11-11 | 8 | 309.93 | 302.42 | -2.4% |
| BBY | 2026-11-11 | 19 | 103.12 | 103.41 | +0.3% |
| CDW | 2026-11-11 | 10 | 171.86 | 172.79 | +0.5% |
| CRWD | 2026-11-11 | 5 | 235.35 | 229.87 | -2.3% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1730.93 | -1.8% |
| RVTY | 2026-11-11 | 10 | 161.07 | 157.02 | -2.5% |
| HPE | 2026-11-11 | 20 | 50.9 | 50.16 | -1.5% |
| WDAY | 2026-11-11 | 10 | 190.49 | 190.64 | +0.1% |
| DLTR | 2026-11-11 | 13 | 139.88 | 141.27 | +1.0% |
| A | 2026-11-11 | 14 | 178.99 | 173.01 | -3.3% |
| IQV | 2026-11-11 | 8 | 276.89 | 271.11 | -2.1% |
| TMO | 2026-11-11 | 3 | 719.69 | 699.44 | -2.8% |
| MPC | 2026-11-11 | 3 | 395.95 | 412.85 | +4.3% |
| ACN | 2026-11-11 | 7 | 255.18 | 249.95 | -2.0% |
| TECH | 2026-11-11 | 72 | 72.83 | 72.84 | +0.0% |

Closed trades: 0, longest losing streak 0.

## v7 — Earnings-led, concentrated: beat streak + SUE + revenue acceleration; buy only stocks in an uptrend that beat last quarter; top 10, checked weekly; sell when a holding drops out of the top 30. Chosen from a 767-config search as the centre of a robust plateau (24 neighbours: dev 7.6-10.0% CAGR, -20% to -26% max DD).

**Orders for the next open:** SELL OXY

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MET | 2026-11-11 | 31 | 102.44 | 101.87 | -0.6% |
| REGN | 2026-11-11 | 3 | 904.99 | 951.19 | +5.1% |
| EXPD | 2026-11-11 | 16 | 190.25 | 195.67 | +2.8% |
| MPC | 2026-11-11 | 8 | 395.95 | 412.85 | +4.3% |
| XEL | 2026-11-11 | 39 | 80.14 | 81.5 | +1.7% |
| FTV | 2026-11-11 | 47 | 67.79 | 67.85 | +0.1% |
| NTAP | 2026-11-11 | 17 | 183.89 | 186.08 | +1.2% |
| UDR | 2026-11-11 | 87 | 36.3 | 36.13 | -0.5% |
| OXY | 2026-11-11 | 55 | 57.26 | 58.4 | +2.0% |
| FRT | 2026-11-11 | 28 | 113.2 | 112.53 | -0.6% |

Closed trades: 0, longest losing streak 0.

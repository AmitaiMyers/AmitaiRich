# Paper trading — v0, v0m, v7 (forward, out-of-sample)

Start 2026-11-10 with $32,000 each; rules frozen; next-open fills; 10 bps/side. Day 11 of paper trading (data to 2026-11-24).

| Account | Days | Value | Return | Max DD | Trades |
|---|---|---|---|---|---|
| v0 | 11 | $30,904 | -3.42% | -7.2% | 2 |
| v0m | 11 | $30,981 | -3.18% | -6.7% | 2 |
| v7 | 11 | $30,955 | -3.27% | -7.1% | 1 |
| BENCH SPY | 11 | $30,661 | -4.09% | -9.1% | 0 |
| BENCH RSP | 11 | $30,972 | -3.12% | -6.8% | 0 |

## v0 — Production Growth Momentum Rider (ROC126 > 25% & close > SMA200; exit close < SMA200), restricted to point-in-time S&P 500 members; 20 positions, 1% risk.

**Orders for the next open:** BUY ROP

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MRNA | 2026-11-11 | 3 | 252.78 | 227.38 | -10.0% |
| CRL | 2026-11-11 | 4 | 347.38 | 336.13 | -3.2% |
| BBY | 2026-11-11 | 19 | 103.12 | 99.62 | -3.4% |
| CDW | 2026-11-11 | 10 | 171.86 | 164.16 | -4.5% |
| CRWD | 2026-11-11 | 5 | 235.35 | 210.86 | -10.4% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1704.0 | -3.3% |
| RVTY | 2026-11-11 | 10 | 161.07 | 153.17 | -4.9% |
| WDAY | 2026-11-11 | 10 | 190.49 | 179.23 | -5.9% |
| DLTR | 2026-11-11 | 13 | 139.88 | 154.65 | +10.6% |
| A | 2026-11-11 | 14 | 178.99 | 183.52 | +2.5% |
| IQV | 2026-11-11 | 8 | 276.89 | 252.01 | -9.0% |
| TMO | 2026-11-11 | 3 | 719.69 | 695.62 | -3.3% |
| MPC | 2026-11-11 | 3 | 394.85 | 355.16 | -10.1% |
| ACN | 2026-11-11 | 7 | 255.18 | 232.32 | -9.0% |
| TECH | 2026-11-11 | 62 | 72.75 | 72.81 | +0.1% |
| VEEV | 2026-11-20 | 7 | 259.25 | 273.62 | +5.5% |
| BDX | 2026-11-20 | 1 | 213.26 | 220.0 | +3.2% |
| SWK | 2026-11-20 | 1 | 107.82 | 109.25 | +1.3% |
| REGN | 2026-11-23 | 1 | 923.18 | 987.09 | +6.9% |

Closed trades: 2, longest losing streak 2.

## v0m — v0 that skips buys after an extreme run-up (6-month momentum above +200%). Owner's idea (2026-11-10, MRNA at +425%): in development 6.5% vs 5.6% CAGR and validation 6.8% vs 5.6%, same max DD; a cap on distance above the 200-MA instead LOST return. Paper-traded only.

**Orders for the next open:** BUY ROP, BUY LH

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| CRL | 2026-11-11 | 4 | 347.38 | 336.13 | -3.2% |
| BBY | 2026-11-11 | 19 | 103.12 | 99.62 | -3.4% |
| CDW | 2026-11-11 | 10 | 171.86 | 164.16 | -4.5% |
| CRWD | 2026-11-11 | 5 | 235.35 | 210.86 | -10.4% |
| MTD | 2026-11-11 | 1 | 1761.8 | 1704.0 | -3.3% |
| RVTY | 2026-11-11 | 10 | 161.07 | 153.17 | -4.9% |
| WDAY | 2026-11-11 | 10 | 190.49 | 179.23 | -5.9% |
| DLTR | 2026-11-11 | 13 | 139.88 | 154.65 | +10.6% |
| A | 2026-11-11 | 14 | 178.99 | 183.52 | +2.5% |
| IQV | 2026-11-11 | 8 | 276.89 | 252.01 | -9.0% |
| TMO | 2026-11-11 | 3 | 719.69 | 695.62 | -3.3% |
| MPC | 2026-11-11 | 3 | 394.85 | 355.16 | -10.1% |
| ACN | 2026-11-11 | 7 | 255.18 | 232.32 | -9.0% |
| TECH | 2026-11-11 | 72 | 72.75 | 72.81 | +0.1% |
| VEEV | 2026-11-20 | 7 | 259.25 | 273.62 | +5.5% |
| BDX | 2026-11-20 | 1 | 213.26 | 220.0 | +3.2% |
| SWK | 2026-11-20 | 1 | 107.82 | 109.25 | +1.3% |
| REGN | 2026-11-23 | 1 | 923.18 | 987.09 | +6.9% |

Closed trades: 2, longest losing streak 2.

## v7 — Earnings-led, concentrated: beat streak + SUE + revenue acceleration; buy only stocks in an uptrend that beat last quarter; top 10, checked weekly; sell when a holding drops out of the top 30. Chosen from a 767-config search as the centre of a robust plateau (24 neighbours: dev 7.6-10.0% CAGR, -20% to -26% max DD).

**Orders for the next open:** none

| Holding | Entry | Shares | Entry price | Last | P&L |
|---|---|---|---|---|---|
| MET | 2026-11-11 | 31 | 102.44 | 99.21 | -3.2% |
| REGN | 2026-11-11 | 3 | 904.07 | 987.09 | +9.2% |
| EXPD | 2026-11-11 | 16 | 190.25 | 197.81 | +4.0% |
| MPC | 2026-11-11 | 8 | 394.85 | 355.16 | -10.1% |
| XEL | 2026-11-11 | 39 | 80.14 | 80.82 | +0.8% |
| FTV | 2026-11-11 | 47 | 67.79 | 65.77 | -3.0% |
| NTAP | 2026-11-11 | 17 | 183.89 | 163.0 | -11.4% |
| UDR | 2026-11-11 | 87 | 36.16 | 36.17 | +0.0% |
| VEEV | 2026-11-11 | 10 | 309.93 | 273.62 | -11.7% |
| APP | 2026-11-17 | 7 | 412.56 | 381.11 | -7.6% |

Closed trades: 1, longest losing streak 0.

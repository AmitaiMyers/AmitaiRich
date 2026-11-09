# SELL-rule tournament — v3 buys, different exits

## Results (sorted by dev + val CAGR)

Same BUY rules and portfolio; only the sell rule changes. Catastrophe stop always on.

| variant | dev CAGR | dev maxDD | dev Sharpe | val CAGR | val maxDD | val Sharpe | trades | avg hold |
|---|---|---|---|---|---|---|---|---|
| MA200 + 1-year time stop | +6.3% | -51% | 0.45 | +9.7% | -24% | 0.56 | 1168 | 73 |
| Rank drop only | +6.8% | -56% | 0.46 | +8.8% | -33% | 0.50 | 1027 | 81 |
| MA200 + rank drop | +5.9% | -50% | 0.43 | +8.6% | -25% | 0.53 | 1695 | 48 |
| Chandelier 6xATR | +7.8% | -52% | 0.51 | +6.1% | -33% | 0.38 | 801 | 105 |
| MA200 break, 3 closes | +6.2% | -53% | 0.43 | +7.6% | -30% | 0.44 | 749 | 114 |
| MA200 break | +6.2% | -49% | 0.45 | +7.1% | -28% | 0.44 | 1066 | 79 |
| MA200 + earnings miss | +6.6% | -49% | 0.47 | +6.4% | -26% | 0.41 | 1224 | 69 |
| Chandelier 4xATR | +6.2% | -59% | 0.44 | +6.3% | -29% | 0.40 | 1716 | 49 |
| MA200 + ADX weakening | +3.7% | -46% | 0.32 | +8.5% | -25% | 0.53 | 3713 | 21 |
| MA200 + OBV weakening | +4.5% | -45% | 0.37 | +6.5% | -22% | 0.44 | 2512 | 33 |
| MA200 + market down | +8.0% | -27% | 0.64 | +2.2% | -19% | 0.22 | 1515 | 45 |
| MA50 break | +3.6% | -43% | 0.33 | +6.0% | -17% | 0.45 | 3442 | 21 |
| MA100 break | +4.2% | -50% | 0.35 | +3.3% | -23% | 0.27 | 2129 | 38 |


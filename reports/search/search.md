# Strategy search — 767 configurations

Scored on development (2005-2018) only; 251 met max DD >= -35% and >= 100 trades. The top 15 by development CAGR were then checked on validation (2019-2022). With this many tries, the best development CAGR is optimistic by construction — the validation column is the honest one.

Benchmarks — SPY: dev +7.5% (DD -55%), val +13.0% (DD -34%). RSP: dev +8.0%, val +13.5%.

| # | Configuration | Dev CAGR | Dev DD | Dev Sharpe | Trades | Invested | Val CAGR | Val DD | Val Sharpe |
|---|---|---|---|---|---|---|---|---|---|
| 1 | ranked earn+reversal | above100 | rankdrop+ma200x3 | 10pos | monthly | +10.3% | -27% | 0.71 | 1342 | 87% | +4.0% | -32% | 0.29 |
| 2 | ranked earn+reversal | none | rankdrop+ma200x3 | 20pos | monthly | +10.1% | -15% | 0.84 | 2188 | 76% | +3.8% | -22% | 0.32 |
| 3 | ranked earn+lowvol | none | rankdrop | 20pos | weekly | +10.0% | -34% | 0.78 | 581 | 98% | +9.3% | -36% | 0.57 |
| 4 | ranked earn3 | above200 | rankdrop+1y | 10pos | weekly | +10.0% | -22% | 0.77 | 377 | 65% | +13.5% | -34% | 0.68 |
| 5 | ranked earn3 | above200 | rankdrop | 10pos | weekly | +9.9% | -22% | 0.77 | 364 | 65% | +13.5% | -34% | 0.68 |
| 6 | ranked earn3 | above200+beat | rankdrop | 10pos | weekly | +9.9% | -22% | 0.77 | 367 | 65% | +14.7% | -33% | 0.73 |
| 7 | ranked earn3 | above200+beat | rankdrop+1y | 10pos | weekly | +9.8% | -22% | 0.76 | 379 | 65% | +14.7% | -33% | 0.73 |
| 8 | ranked earn+lowvol | none | rankdrop+ma200x3 | 10pos | monthly | +9.6% | -24% | 0.88 | 529 | 90% | +5.9% | -24% | 0.47 |
| 9 | ranked earn+reversal | none | rankdrop+ma200x3 | 30pos | monthly | +9.4% | -19% | 0.78 | 2827 | 81% | +6.2% | -20% | 0.49 |
| 10 | ranked earn3 | above100 | rankdrop | 10pos | weekly | +9.4% | -21% | 0.73 | 380 | 65% | +8.2% | -36% | 0.48 |
| 11 | ranked earn3 | above200 | rankdrop+ma200x3 | 10pos | weekly | +9.3% | -23% | 0.73 | 503 | 65% | +12.7% | -31% | 0.67 |
| 12 | ranked earn3 | above200+beat | rankdrop+ma200x3 | 10pos | weekly | +9.3% | -23% | 0.73 | 506 | 65% | +12.6% | -31% | 0.66 |
| 13 | ranked earn3 | above100 | rankdrop+ma200x3 | 10pos | weekly | +9.3% | -20% | 0.74 | 491 | 65% | +9.4% | -34% | 0.53 |
| 14 | ranked earn+growth | above200 | rankdrop+1y | 10pos | weekly | +9.3% | -23% | 0.67 | 410 | 66% | +21.3% | -35% | 0.94 |
| 15 | ranked earn+growth | above200+beat | rankdrop+1y | 10pos | weekly | +9.2% | -24% | 0.67 | 411 | 66% | +22.1% | -35% | 0.97 |

Configurations beating SPY's CAGR in BOTH periods (among those checked): 6.

## Development CAGR by family (all configurations)

| Family | Configs | Best dev CAGR | Median dev CAGR | Median dev DD |
|---|---|---|---|---|
| ranked beat | 72 | +6.0% | +0.1% | -29% |
| ranked earn+growth | 72 | +9.3% | +8.2% | -24% |
| ranked earn+lowvol | 72 | +10.9% | +8.6% | -42% |
| ranked earn+reversal | 72 | +12.2% | +7.7% | -47% |
| ranked earn+trend | 72 | +7.7% | +6.3% | -56% |
| ranked earn3 | 72 | +10.0% | +8.1% | -21% |
| ranked everything | 72 | +7.7% | +6.5% | -52% |
| ranked momentum | 72 | +5.6% | +2.9% | -62% |
| ranked pead | 72 | +8.1% | +5.5% | -58% |
| ranked quality | 72 | +6.8% | +5.4% | -19% |
| rider donchian | 3 | +6.6% | +5.7% | -45% |
| rider momentum | 32 | +6.5% | +4.5% | -44% |
| rider trend | 6 | +6.4% | +4.9% | -35% |
| rider vol-adj | 6 | +8.2% | +6.6% | -43% |

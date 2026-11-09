# Control portfolios — is the machinery neutral?

Random selections run through the identical engine, costs and fills. Held random 20 should track RSP (equal-weight S&P 500); rotation costs only trading costs if the machinery is sound.

## Controls

| variant | dev CAGR | dev maxDD | dev Sharpe | val CAGR | val maxDD | val Sharpe | trades |
|---|---|---|---|---|---|---|---|
| random 20, held | +7.0% | -56% | 0.43 | +16.2% | -40% | 0.71 | 87 |
| random 20, re-drawn monthly | +5.1% | -66% | 0.35 | +7.4% | -43% | 0.42 | 3742 |
| random 20 held + MA200 exit | +5.2% | -26% | 0.48 | +8.9% | -18% | 0.68 | 1529 |


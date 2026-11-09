# Control portfolios — is the machinery neutral?

Random selections run through the identical engine, costs and fills. Held random 20 should track RSP (equal-weight S&P 500); rotation costs only trading costs if the machinery is sound.

## Controls

| variant | dev CAGR | dev maxDD | dev Sharpe | val CAGR | val maxDD | val Sharpe | trades |
|---|---|---|---|---|---|---|---|
| random 20, held | +6.1% | -57% | 0.37 | +21.8% | -40% | 0.80 | 150 |
| random 20, re-drawn monthly | +4.9% | -71% | 0.33 | +15.0% | -44% | 0.65 | 4118 |
| random 20 held + MA200 exit | +4.6% | -28% | 0.40 | +10.3% | -25% | 0.66 | 1622 |


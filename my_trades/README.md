# My trades

Your own buys and sells, exported from the app (My positions → **Export trade log**).
Upload the newest `my-trades-YYYY-MM-DD.csv` here now and then (GitHub → this folder → Add file →
Upload files) so your real results can later be compared with the v0 / v7 signals and the paper accounts.

Columns: `status` (open/closed), `ticker`, `entry_date`, `entry_price`, `shares`, `exit_date`,
`exit_price`, `return_pct`, `app_verdict` + `app_reason` (the app's HOLD/SELL call when you recorded
the sale, or today's call for open positions).

The automatic logs live in `signal_log/`:
- `history.csv` — every day's v0 and v7 lists
- `list_exits.csv` — names that left a list each day, with the reason
- `paper_trades.csv` — every buy and sell of the v0, v0m and v7 paper accounts

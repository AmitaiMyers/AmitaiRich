# Deploying Roof Signals (the PWA) with GitHub

Everything runs on GitHub's free infrastructure. No server, no API keys.

## One-time setup

1. **Merge to the default branch.** Scheduled workflows only run on the default branch (`main`).
2. **Enable Pages from Actions:** repository **Settings → Pages → Build and deployment → Source:
   "GitHub Actions"**.
3. **First deploy:** **Actions → Publish PWA → Run workflow**. When it finishes, the site is at
   `https://<your-user>.github.io/<repo>/` (the deploy job prints the URL).
4. **Install it:** open the URL on your phone → *Add to Home Screen* (iOS: Share menu; Android:
   the install prompt / ⋮ menu). It works offline for anything you have already opened.

> Privacy: a Pages site is public to anyone with the URL (and a Pages site for a private repo
> requires a paid GitHub plan). Nothing private is published: your positions live only in your
> browser. Import your `positions.csv` on the Positions page — it never leaves the device.

## What runs when

| Workflow | Trigger | What it does |
|---|---|---|
| **CI** (`ci.yml`) | every push / PR | Python tests, exact JS-parity tests, demo site build |
| **Publish PWA** (`publish.yml`) | weekdays 22:17 UTC (after the US close), after a successful Research run, or manually | downloads fresh daily data for the S&P 500, Nasdaq-100, watchlist and Magic Formula lists, runs the production scan, builds `site/` and deploys it to Pages |
| **Paper trading** (`paper.yml`) | weekdays 21:37 UTC, or manually | replays v0 and v7 from 2026-11-10 on fresh data, commits `reports/paper/paper.md` (holdings + next-open orders), then Publish PWA shows it — needs the `SEC_USER_AGENT` repository variable |
| **Strategy lab** (`lab.yml`) | manual | any lab command on fresh data (needs `SEC_USER_AGENT`) |
| **Research** (`research.yml`) | manual (choose a phase; default `v3`) | runs the research on GitHub's runners, uploads the full output as an artifact, commits `research_results/<phase>.json`, then Publish PWA redeploys so the report appears on the Research page |

The research workflow **never changes the production strategy**. If `v3` promotes a candidate,
switching `scan_today.DEFAULT_BUY / DEFAULT_CONFIG` is a reviewed code change.

## Preview locally

```bash
python publish.py --out site --demo       # synthetic data, fully offline
python -m http.server 8000 --directory site
```
Then open http://localhost:8000. Without `--demo`, `publish.py` downloads real data (network needed).

## Troubleshooting

- **Publish fails downloading data:** Yahoo occasionally rate-limits shared runners. Re-run the
  workflow; tickers that still fail are listed in `data/manifest.json` (`failed`) and skipped.
- **The app shows old data:** the service worker serves the cached shell. Reopen the app; when a
  new build is detected a banner says so.

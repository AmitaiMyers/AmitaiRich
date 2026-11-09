"""Daily push notification: today's NEW stocks from v0 and v7 (run by the Publish PWA job).

    python notify.py signal_log/latest.json

Needs two GitHub secrets: VAPID_PRIVATE_KEY and PUSH_SUBSCRIPTION (the JSON the app shows
under "Notifications"; a JSON list of several subscriptions also works, e.g. phone + laptop).
If either is missing the job prints why and exits 0 — notifications are optional, the site is not.
Positions live only on the phone, so the push points to the app for their HOLD/SELL status.
"""

import json
import os
import sys

import webpush

MAX_NAMES = 6


def _names(tickers):
    shown = ", ".join(tickers[:MAX_NAMES])
    return shown + (f" +{len(tickers) - MAX_NAMES}" if len(tickers) > MAX_NAMES else "")


def message(daily):
    """(title, body) for the day's push."""
    if not daily["available"]:
        return "Roof Signals", f"No daily lists yet ({daily['reason']}). Tap to check your positions."
    parts = []
    for key in ("v0", "v7"):
        new = daily[key]["new"]
        parts.append(f"{key}: {_names(new)}" if new else f"{key}: no new buys")
    return f"Roof Signals · {daily['date']}", " · ".join(parts) + ". Tap for your positions' HOLD/SELL."


def main(path):
    for name in ("VAPID_PRIVATE_KEY", "PUSH_SUBSCRIPTION"):
        if not os.environ.get(name):
            print(f"{name} is not set — skipping the push notification.")
            return 0
    if os.path.exists(path):
        with open(path) as fh:
            daily = {**json.load(fh), "available": True}
    else:
        daily = {"available": False, "reason": f"{path} not found"}
    title, body = message(daily)
    subscriptions = json.loads(os.environ["PUSH_SUBSCRIPTION"])
    for subscription in subscriptions if isinstance(subscriptions, list) else [subscriptions]:
        status = webpush.send(subscription, {"title": title, "body": body, "url": "./#/today"},
                              os.environ["VAPID_PRIVATE_KEY"])
        print(f"push sent ({status}): {title} — {body}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

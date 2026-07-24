"""Recorder CLI — capture REAL live crypto sessions for replay in the simulator.

Records the full order book + trades from Binance's public API (no key/signup)
for one or more symbols, concurrently, for a chosen duration, and saves each as a
JSON session the server can replay. Because real Level-2 depth only exists live,
recording is REAL-TIME: `--minutes 3` takes 3 minutes.

Usage (from the repo root):
    python -m sim.crypto_record                          # BTC+ETH+SOL, 3 min, depth 100
    python -m sim.crypto_record --minutes 5 --symbols BTCUSDT ETHUSDT
    python -m sim.crypto_record --seconds 120 --depth 50 --symbols BTCUSDT

All symbols in a run share one recording id (a UTC timestamp) so they replay as a
single "recording" (the crypto analogue of a trading-day session).
"""

import argparse
import sys
import threading
from datetime import datetime, timezone

from errors import SimulatorError
from sim.crypto_source import CRYPTO_SYMBOLS, record_session
from sim import store

DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def _record_one(symbol, seconds, depth, recid, results, progress):
    try:
        def on_tick(i, total):
            progress[symbol] = i
        session = record_session(symbol, seconds, depth=depth, on_tick=on_tick)
        path = store.save_crypto_session(session, recid)
        results[symbol] = ("ok", path)
    except SimulatorError as exc:
        results[symbol] = ("error", str(exc))
    except Exception as exc:  # noqa: BLE001 — a recorder thread must not die silently
        results[symbol] = ("error", repr(exc))


def record(symbols, seconds, depth, recid=None):
    """Record `symbols` concurrently for `seconds`. Returns (recid, results)."""
    for s in symbols:
        if s not in CRYPTO_SYMBOLS:
            raise SimulatorError(f"Unknown symbol {s!r}; expected {list(CRYPTO_SYMBOLS)}")
    recid = recid or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results, progress = {}, {s: 0 for s in symbols}
    threads = [threading.Thread(target=_record_one, args=(s, seconds, depth, recid, results, progress))
               for s in symbols]

    print(f"Recording {len(symbols)} symbol(s) for {seconds}s (depth {depth}) "
          f"-> recording {recid}\nThis is REAL-TIME; please wait ~{seconds}s.\n")
    for t in threads:
        t.start()

    # simple live progress line
    import time
    done = False
    while not done:
        time.sleep(2)
        done = all(not t.is_alive() for t in threads)
        line = "  ".join(f"{s}:{progress[s]}/{seconds}" for s in symbols)
        print(f"  {line}", flush=True)
    for t in threads:
        t.join()

    print()
    ok = 0
    for s in symbols:
        status, info = results.get(s, ("error", "no result"))
        if status == "ok":
            ok += 1
            print(f"  {s}: saved -> {info}")
        else:
            print(f"  {s}: ERROR: {info}")
    print(f"\nDone. {ok}/{len(symbols)} symbols recorded as recording {recid}.")
    return recid, results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Record real live crypto sessions.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS,
                        help=f"Symbols to record (default {DEFAULT_SYMBOLS}). Options: {list(CRYPTO_SYMBOLS)}")
    parser.add_argument("--minutes", type=float, help="Recording length in minutes.")
    parser.add_argument("--seconds", type=int, help="Recording length in seconds (overrides --minutes).")
    parser.add_argument("--depth", type=int, default=50,
                        help="Order-book levels per side to capture (default 50).")
    args = parser.parse_args(argv)

    seconds = args.seconds if args.seconds else int((args.minutes or 3) * 60)
    if seconds < 1:
        parser.error("recording length must be >= 1 second")

    _, results = record(args.symbols, seconds, args.depth)
    failures = [s for s, (status, _) in results.items() if status != "ok"]
    return 1 if len(failures) == len(args.symbols) else 0


if __name__ == "__main__":
    sys.exit(main())

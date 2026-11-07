"""Day-trading simulator ("ROOF·SIM").

A real-time, second-by-second paper-trading practice app built on real Yahoo
Finance data. Yahoo's finest free granularity is the 1-minute bar, so the
ingestion pipeline downloads real 1m bars and deterministically interpolates
them down to per-second ticks (anchored on each bar's real Open/High/Low/Close),
saving finished sessions as JSON. The FastAPI server (`sim.server`) serves those
sessions to a canvas front-end that renders candlesticks, a synthetic order book,
a time-and-sales tape, positions/fills blotter and full playback controls.
"""

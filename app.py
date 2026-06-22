"""Module 5 — Streamlit dashboard.

Control panel (sidebar) to configure and launch a backtest, KPI tiles, an
interactive Plotly candlestick chart with Bollinger Bands and BUY/SELL markers
read from the trade ledger, and an equity curve.

Run with:  streamlit run app.py
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import database
import indicators
import universe
from algorithms import ALGORITHMS, build_algorithm
from batch import PER_TICKER_ERRORS, compute_batch_summary, run_batch
from data_engine import fetch_data
from scan_today import check_holding, scan_for_buys
from simulation import compute_kpis, run_simulation

st.set_page_config(page_title="Capital Market Roof Simulator", layout="wide")
st.title("📈 Capital Market Roof Simulator")
st.caption("Local, zero-cost backtesting of breakout strategies on historical stock data.")

PRESET_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY", "QQQ", "Custom…"]
FLAGSHIP_NAME = "Bollinger Squeeze + Volume Breakout"
SCANNER_NAME = "Roof: 52-Week-High Breakout"  # research-recommended daily scanner

# Universe scope labels for "Scan today" -> universe.get_universe scope code.
SCAN_SCOPES = {
    "S&P 500 + Nasdaq-100": "sp500_ndx",
    "S&P 500": "sp500",
    "Nasdaq-100": "nasdaq100",
}

# Friendly candle-interval label -> yfinance interval code.
INTERVAL_OPTIONS = {"Hourly": "1h", "Daily": "1d", "Weekly": "1wk", "Monthly": "1mo"}

# Default universe for batch scans (~30 large-cap names); editable in the sidebar.
DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "WMT",
    "JNJ", "PG", "MA", "HD", "CVX", "KO", "PEP", "COST", "MCD", "DIS",
    "CSCO", "INTC", "AMD", "NFLX", "ADBE", "CRM", "BA", "CAT", "GS", "IBM",
]


def _algo_index(default_name):
    names = list(ALGORITHMS.keys())
    return names.index(default_name) if default_name in names else 0


def render_sidebar():
    """Collect every run parameter and return it as a dict."""
    with st.sidebar:
        st.header("Configuration")

        mode = st.radio(
            "Mode", ["Single stock", "Batch scan", "Scan today"],
            help="Single = one ticker with full charts. Batch = backtest one strategy "
                 "across many tickers. Scan today = which stocks fire a BUY on the "
                 "latest bar, across the whole market.",
        )

        ticker = "AAPL"
        tickers = []
        scan_scope = "sp500_ndx"
        as_of = pd.Timestamp.today().normalize()
        if mode == "Scan today":
            scope_label = st.selectbox("Universe to scan", list(SCAN_SCOPES.keys()), index=0)
            scan_scope = SCAN_SCOPES[scope_label]
            as_of = st.date_input("Scan as of", value=pd.Timestamp.today().normalize(),
                                  help="Which day's close to scan. Defaults to today.")
            st.caption("First run downloads data for the whole universe (slow); "
                       "repeat runs the same day are cached.")
        if mode == "Single stock":
            ticker_choice = st.selectbox("Ticker", PRESET_TICKERS, index=0)
            ticker = (
                st.text_input("Custom ticker", value="AAPL").strip().upper()
                if ticker_choice == "Custom…"
                else ticker_choice
            )
        else:
            selected = st.multiselect(
                "Universe", DEFAULT_UNIVERSE, default=DEFAULT_UNIVERSE,
                help="Pick from the default universe, and/or add more below.",
            )
            extra_raw = st.text_area(
                "Extra tickers (comma / space / newline separated)", value="",
                placeholder="e.g. ORCL, QCOM, T",
            )
            extra = [tok for tok in extra_raw.replace(",", " ").split()]
            tickers = selected + extra
            st.caption(f"{len(tickers)} ticker(s) queued for the scan.")

        start_date = st.date_input("Start date", value=pd.to_datetime("2018-01-01"))
        end_date = st.date_input("End date", value=pd.to_datetime("2023-12-31"))

        interval_label = st.selectbox(
            "Candle interval", list(INTERVAL_OPTIONS.keys()), index=1,
            help="Candle size for both data and signals. Hourly only has ~730 days "
                 "of history on Yahoo — use a recent date range for it.",
        )
        interval = INTERVAL_OPTIONS[interval_label]
        if interval == "1h":
            st.warning("Hourly data is limited to ~the last 730 days. Pick a recent date range.")

        starting_capital = st.number_input(
            "Starting capital ($)", min_value=100.0, value=10_000.0, step=1_000.0
        )

        algo_names = list(ALGORITHMS.keys())
        default_buy = SCANNER_NAME if mode == "Scan today" else FLAGSHIP_NAME
        buy_name = st.selectbox("Buy strategy", algo_names, index=_algo_index(default_buy))
        if mode == "Scan today":
            sell_name = buy_name  # the buy scan does not use exit logic
        else:
            sell_name = st.selectbox("Sell strategy", algo_names, index=_algo_index(FLAGSHIP_NAME))

        st.subheader("Test toggles")
        stop_mode = st.selectbox(
            "Stop-loss mode", ["tightest", "widest"],
            help="tightest = smallest loss (highest stop); widest = most room (lowest stop).",
        )
        sizing_mode = st.selectbox(
            "Position sizing", ["risk_based", "all_in", "fixed_fraction"],
            help="risk_based needs a strategy that defines a stop (not the Dummy).",
        )
        risk_pct = st.slider("Risk % per trade (risk_based)", 0.1, 5.0, 1.0, 0.1) / 100.0
        fixed_fraction = st.slider("Equity fraction % (fixed_fraction)", 10, 100, 95, 5) / 100.0
        fill_mode = st.selectbox(
            "Fill timing", ["close", "next_open"],
            help="close = fill at signal day's close; next_open = fill at next day's open.",
        )

        with st.expander("Bollinger strategy parameters"):
            bb_period = int(st.number_input("BB period", 5, 100, 20))
            bb_std = float(st.number_input("BB std", 1.0, 4.0, 2.0, 0.5))
            bandwidth_threshold = float(st.number_input("Bandwidth threshold", 0.01, 1.0, 0.10, 0.01))
            min_squeeze_candles = int(st.number_input("Min squeeze candles", 1, 30, 5))
            vol_avg_period = int(st.number_input("Volume avg period", 5, 60, 20))
            vol_breakout_mult = float(st.number_input("Volume breakout multiple", 1.0, 5.0, 1.5, 0.1))
            atr_period = int(st.number_input("ATR period", 2, 50, 14))
            atr_mult = float(st.number_input("ATR multiple", 0.5, 6.0, 2.0, 0.5))
            swing_lookback = int(st.number_input("Swing lookback", 2, 60, 10))

        with st.expander("Optional strategy parameters (SMA)"):
            fast_period = int(st.number_input("SMA fast period", 2, 100, 20))
            slow_period = int(st.number_input("SMA slow period", 5, 300, 50))
            hold_bars = int(st.number_input("Dummy hold bars", 1, 60, 5))

        with st.expander("Breakout (roof) parameters", expanded=(mode == "Scan today")):
            roof_lookback = int(st.number_input(
                "Roof lookback (bars; 252 = 52-week high)", 20, 1000, 252))
            vol_surge_mult = float(st.number_input(
                "Volume surge × average (0 = off)", 0.0, 5.0, 1.5, 0.1))
            use_htf = 1 if st.checkbox("Require weekly-trend agreement", value=False) else 0

        use_cache = st.checkbox("Use local price cache", value=True)
        button_labels = {"Batch scan": "🚀 Run Scan", "Scan today": "🔭 Scan Today"}
        button_label = button_labels.get(mode, "🚀 Run Simulation")
        run_clicked = st.button(button_label, type="primary", use_container_width=True)

    return {
        "mode": mode,
        "ticker": ticker,
        "tickers": tickers,
        "scan_scope": scan_scope,
        "as_of": str(as_of),
        "start_date": str(start_date),
        "end_date": str(end_date),
        "interval": interval,
        "starting_capital": starting_capital,
        "buy_name": buy_name,
        "sell_name": sell_name,
        "stop_mode": stop_mode,
        "sizing_mode": sizing_mode,
        "risk_pct": risk_pct,
        "fixed_fraction": fixed_fraction,
        "fill_mode": fill_mode,
        "use_cache": use_cache,
        "run_clicked": run_clicked,
        # algorithm parameters (a superset; build_algorithm filters per strategy)
        "bb_period": bb_period,
        "bb_std": bb_std,
        "bandwidth_threshold": bandwidth_threshold,
        "min_squeeze_candles": min_squeeze_candles,
        "vol_avg_period": vol_avg_period,
        "vol_breakout_mult": vol_breakout_mult,
        "atr_period": atr_period,
        "atr_mult": atr_mult,
        "swing_lookback": swing_lookback,
        "fast_period": fast_period,
        "slow_period": slow_period,
        "hold_bars": hold_bars,
        "roof_lookback": roof_lookback,
        "vol_surge_mult": vol_surge_mult,
        "use_htf": use_htf,
    }


def execute_run(params):
    """Build the algorithms, run the simulation, and stash results in session state."""
    buy_algo = build_algorithm(params["buy_name"], params)
    sell_algo = build_algorithm(params["sell_name"], params)
    run_id = run_simulation(
        ticker=params["ticker"],
        start_date=params["start_date"],
        end_date=params["end_date"],
        starting_capital=params["starting_capital"],
        buy_algo=buy_algo,
        sell_algo=sell_algo,
        stop_mode=params["stop_mode"],
        sizing_mode=params["sizing_mode"],
        risk_pct=params["risk_pct"],
        fixed_fraction=params["fixed_fraction"],
        fill_mode=params["fill_mode"],
        interval=params["interval"],
        use_cache=params["use_cache"],
    )
    st.session_state["result_kind"] = "single"
    st.session_state["run_id"] = run_id
    st.session_state["params"] = params


def execute_batch(params):
    """Build the algorithms, scan every ticker, and stash the batch in session state."""
    buy_algo = build_algorithm(params["buy_name"], params)
    sell_algo = build_algorithm(params["sell_name"], params)
    batch_id = run_batch(
        tickers=params["tickers"],
        start_date=params["start_date"],
        end_date=params["end_date"],
        starting_capital=params["starting_capital"],
        buy_algo=buy_algo,
        sell_algo=sell_algo,
        stop_mode=params["stop_mode"],
        sizing_mode=params["sizing_mode"],
        risk_pct=params["risk_pct"],
        fixed_fraction=params["fixed_fraction"],
        fill_mode=params["fill_mode"],
        interval=params["interval"],
        use_cache=params["use_cache"],
    )
    st.session_state["result_kind"] = "batch"
    st.session_state["batch_id"] = batch_id
    st.session_state["params"] = params


def execute_scan(params):
    """Run the daily BUY scan across the chosen universe; stash hits in session state."""
    tickers = universe.get_universe(params["scan_scope"], use_cache=params["use_cache"])
    buy_algo = build_algorithm(params["buy_name"], params)
    hits, errors = scan_for_buys(
        tickers, buy_algo, as_of=params["as_of"],
        interval=params["interval"], use_cache=params["use_cache"],
    )
    st.session_state["result_kind"] = "scan"
    st.session_state["scan_hits"] = hits
    st.session_state["scan_errors"] = errors
    st.session_state["scan_universe_size"] = len(tickers)
    st.session_state["params"] = params


def build_price_chart(df, trades, bb_period, bb_std):
    """Candlestick + Bollinger Bands + BUY/SELL markers from the ledger."""
    middle, upper, lower = indicators.bollinger_bands(df["Close"], bb_period, bb_std)
    band_line = dict(width=1)

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
            name="Price",
        )
    )
    fig.add_trace(go.Scatter(x=df.index, y=upper, name="Upper BB", line=dict(color="#8fa8ff", **band_line)))
    fig.add_trace(go.Scatter(x=df.index, y=middle, name="Middle BB", line=dict(color="#aaaaaa", dash="dot", **band_line)))
    fig.add_trace(go.Scatter(x=df.index, y=lower, name="Lower BB", line=dict(color="#8fa8ff", **band_line)))

    buys = trades[trades["trade_type"] == "BUY"]
    sells = trades[trades["trade_type"] == "SELL"]
    fig.add_trace(
        go.Scatter(
            x=pd.to_datetime(buys["date"]), y=buys["price"], mode="markers", name="BUY",
            marker=dict(symbol="triangle-up", color="#1bbf5c", size=13, line=dict(width=1, color="#0a5")),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=pd.to_datetime(sells["date"]), y=sells["price"], mode="markers", name="SELL",
            marker=dict(symbol="triangle-down", color="#e5443b", size=13, line=dict(width=1, color="#900")),
        )
    )
    fig.update_layout(
        xaxis_rangeslider_visible=False, height=620, legend=dict(orientation="h"),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    return fig


def build_equity_chart(equity):
    """Line chart of total portfolio equity over time."""
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=pd.to_datetime(equity["date"]), y=equity["total_equity"],
            mode="lines", name="Total Equity", line=dict(color="#1bbf5c", width=2),
        )
    )
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10))
    return fig


def render_results():
    """Render KPIs, charts, and the trade ledger for the most recent run."""
    run_id = st.session_state["run_id"]
    params = st.session_state["params"]

    conn = database.get_connection()
    kpis = compute_kpis(conn, run_id)
    trades = database.get_trades(conn, run_id)
    equity = database.get_equity_curve(conn, run_id)
    conn.close()

    st.subheader(f"Results — {params['ticker']} · {params['interval']} candles  (run #{run_id})")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Return", f"{kpis['total_return'] * 100:.2f}%")
    col2.metric("Final Equity", f"${kpis['final_equity']:,.2f}")
    col3.metric("Round-trip Trades", f"{kpis['num_trades']}")
    col4.metric("Win Rate", f"{kpis['win_rate'] * 100:.1f}%")

    df = fetch_data(
        params["ticker"], params["start_date"], params["end_date"],
        interval=params["interval"], use_cache=True,
    )
    st.plotly_chart(
        build_price_chart(df, trades, params["bb_period"], params["bb_std"]),
        use_container_width=True,
    )

    if len(equity):
        st.markdown("**Equity curve**")
        st.plotly_chart(build_equity_chart(equity), use_container_width=True)

    st.markdown("**Trade ledger**")
    st.dataframe(trades, use_container_width=True, hide_index=True)


def build_returns_bar(ok_results):
    """Horizontal-friendly bar chart of per-ticker total return (sorted), green/red."""
    chart_df = ok_results.sort_values("total_return")
    colors = ["#1bbf5c" if r > 0 else "#e5443b" for r in chart_df["total_return"]]
    fig = go.Figure(
        go.Bar(x=chart_df["ticker"], y=chart_df["total_return"] * 100, marker_color=colors)
    )
    fig.update_layout(
        height=360, margin=dict(l=10, r=10, t=30, b=10),
        yaxis_title="Total return (%)", xaxis_title="Ticker",
    )
    return fig


def render_batch_results():
    """Render the aggregate summary, per-ticker table, return chart, and drill-down."""
    batch_id = st.session_state["batch_id"]
    params = st.session_state["params"]

    conn = database.get_connection()
    batch = database.get_batch(conn, batch_id)
    summary = compute_batch_summary(conn, batch_id)
    results = database.get_batch_results(conn, batch_id)
    conn.close()

    st.subheader(
        f"Batch scan #{batch_id} — {batch['buy_algorithm']} / {batch['sell_algorithm']} "
        f"· {batch['interval']} candles"
    )

    row1 = st.columns(4)
    row1[0].metric("Stocks scanned", summary["n_total"])
    row1[1].metric("Traded", summary["n_traded"], help="Stocks the strategy actually entered.")
    row1[2].metric("No-trade / Failed", f"{summary['n_no_trades']} / {summary['n_failed']}")
    row1[3].metric("Profitable (of traded)", f"{summary['pct_profitable'] * 100:.0f}%")

    row2 = st.columns(4)
    row2[0].metric("Avg return (traded)", f"{summary['avg_return'] * 100:.2f}%")
    row2[1].metric("Median return", f"{summary['median_return'] * 100:.2f}%")
    row2[2].metric("Avg win rate", f"{summary['avg_win_rate'] * 100:.1f}%")
    row2[3].metric("Total trades", summary["total_trades"])

    if summary["best_ticker"] is not None:
        st.caption(
            f"🏆 Best: **{summary['best_ticker']}** {summary['best_return'] * 100:+.1f}%   ·   "
            f"📉 Worst: **{summary['worst_ticker']}** {summary['worst_return'] * 100:+.1f}%   ·   "
            f"avg {summary['avg_trades']:.1f} trades/stock"
        )

    ok_results = results[results["status"] == "ok"]
    if len(ok_results):
        st.markdown("**Per-ticker total return**")
        st.plotly_chart(build_returns_bar(ok_results), use_container_width=True)

    st.markdown("**Per-ticker results**")
    display = results.copy()
    display["return_%"] = (display["total_return"] * 100).round(2)
    display["win_%"] = (display["win_rate"] * 100).round(1)
    display = display[
        ["ticker", "status", "return_%", "num_trades", "win_%", "final_equity", "error_message"]
    ].sort_values("return_%", ascending=False, na_position="last")
    st.dataframe(display, use_container_width=True, hide_index=True)

    # Drill-down: inspect any successfully-run ticker's candlestick chart.
    traded_tickers = ok_results[ok_results["num_trades"] > 0]["ticker"].tolist()
    if traded_tickers:
        st.markdown("**Inspect a ticker**")
        chosen = st.selectbox("Ticker", traded_tickers)
        chosen_run_id = int(ok_results[ok_results["ticker"] == chosen]["run_id"].iloc[0])
        conn = database.get_connection()
        trades = database.get_trades(conn, chosen_run_id)
        conn.close()
        chosen_df = fetch_data(
            chosen, params["start_date"], params["end_date"],
            interval=params["interval"], use_cache=True,
        )
        st.plotly_chart(
            build_price_chart(chosen_df, trades, params["bb_period"], params["bb_std"]),
            use_container_width=True,
        )


def render_scan_results():
    """Render today's BUY candidates across the scanned universe + a holdings check."""
    params = st.session_state["params"]
    hits = st.session_state["scan_hits"]
    errors = st.session_state["scan_errors"]
    n_universe = st.session_state["scan_universe_size"]

    st.subheader(f"Scan today — {params['buy_name']}  ·  as of {params['as_of'][:10]}")
    cols = st.columns(4)
    cols[0].metric("Universe scanned", n_universe)
    cols[1].metric("BUY signals", len(hits))
    cols[2].metric("No data", len(errors))
    cols[3].metric("Volume filter",
                   f"{params['vol_surge_mult']:g}× avg" if params["vol_surge_mult"] else "off")

    if hits.empty:
        st.info("No stocks broke their roof on volume on this bar — a normal outcome "
                "(breakouts are rare). Try another date, a different universe, or relax "
                "the roof / volume parameters in the sidebar.")
    else:
        st.markdown("**Stocks to consider buying** (largest volume surge first)")
        st.dataframe(hits, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇ Download buy list (CSV)", hits.to_csv(index=False),
            file_name=f"buys_{params['as_of'][:10]}.csv", mime="text/csv",
        )

    st.markdown("---")
    st.markdown("**Already holding something? Check if today says sell.**")
    hc = st.columns([1.2, 1, 1, 0.8])
    hold_ticker = hc[0].text_input("Ticker held", value="", key="hold_ticker").strip().upper()
    hold_entry_date = hc[1].date_input("Entry date", value=pd.Timestamp.today().normalize(),
                                       key="hold_entry_date")
    hold_entry_price = hc[2].number_input("Entry price ($, 0 = use close)", min_value=0.0,
                                          value=0.0, key="hold_entry_price")
    check_clicked = hc[3].button("Check", use_container_width=True)
    if check_clicked and hold_ticker:
        algo = build_algorithm(params["buy_name"], params)
        try:
            verdict = check_holding(
                hold_ticker, algo, str(hold_entry_date),
                entry_price=(hold_entry_price or None), as_of=params["as_of"],
                stop_mode=params["stop_mode"], interval=params["interval"],
                use_cache=params["use_cache"],
            )
        except PER_TICKER_ERRORS as exc:
            st.warning(f"Couldn't check {hold_ticker}: {exc}")
        else:
            badge = "🟢" if verdict["verdict"] == "HOLD" else "🔴"
            st.markdown(
                f"{badge} **{verdict['verdict']}** — {verdict['reason']}   ·   "
                f"entry ${verdict['entry_price']} → last ${verdict['last_close']} "
                f"(**{verdict['open_pnl_%']:+.1f}%**)   ·   stop ${verdict['stop_price']}   ·   "
                f"{verdict['bars_held']} bars held"
            )
    elif check_clicked:
        st.warning("Enter a ticker to check.")


params = render_sidebar()
if params["run_clicked"]:
    if params["mode"] == "Batch scan":
        with st.spinner(f"Scanning {len(params['tickers'])} stocks… (first run downloads data)"):
            execute_batch(params)
    elif params["mode"] == "Scan today":
        with st.spinner("Scanning the universe for breakouts… (first run downloads data)"):
            execute_scan(params)
    else:
        with st.spinner("Running simulation…"):
            execute_run(params)

if "result_kind" in st.session_state:
    kind = st.session_state["result_kind"]
    if kind == "batch":
        render_batch_results()
    elif kind == "scan":
        render_scan_results()
    else:
        render_results()
else:
    st.info("Configure a run in the sidebar and click **Run**.")

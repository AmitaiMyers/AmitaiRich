"""Module 5 — Streamlit dashboard.

Control panel (sidebar) to configure and launch a backtest, KPI tiles, an
interactive Plotly candlestick chart with the strategy's own overlay and BUY/SELL
markers read from the trade ledger, and an equity curve.

Modes: one stock, an independent per-stock batch scan, a realistic shared-capital
PORTFOLIO backtest (the research system, vs equal-weight and SPY buy & hold), and
"scan today" (the production BUY list).

Strategy parameters are generated from the SELECTED strategy's own DEFAULTS (seeded
with the production config for the production strategy). The sidebar used to send
one superset of Bollinger-panel values to every strategy, which silently replaced
e.g. the Momentum Rider's atr_mult 4.0 / atr_period 20 / swing_lookback 20 with
2.0 / 14 / 10 — a different system from the one the research validated.

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
from data_engine import fetch_data, prefetch
from portfolio import (PortfolioConfig, buy_and_hold_portfolio, equity_metrics,
                       run_portfolio, single_asset_benchmark)
from scan_today import DEFAULT_BUY, DEFAULT_CONFIG, DEFAULT_STOP_MODE, TARGET_POSITIONS, check_holding, scan_for_buys
from simulation import compute_kpis, run_simulation

st.set_page_config(page_title="Capital Market Roof Simulator", layout="wide")
st.title("📈 Capital Market Roof Simulator")
st.caption("Local, zero-cost backtesting of trend and breakout strategies on historical stock data.")

PRESET_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY", "QQQ", "Custom…"]
MODES = ("Single stock", "Batch scan", "Portfolio backtest", "Scan today")
RUN_LABELS = {"Single stock": "🚀 Run Simulation", "Batch scan": "🚀 Run Scan",
              "Portfolio backtest": "🚀 Run Portfolio", "Scan today": "🔭 Scan Today"}
SAME_AS_BUY = "(same as buy strategy)"

# Universe scope labels -> universe.get_universe scope code.
SCAN_SCOPES = {
    "S&P 500 + Nasdaq-100": "sp500_ndx",
    "S&P 500": "sp500",
    "Nasdaq-100": "nasdaq100",
    "Watchlist": "watchlist",
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
    return list(ALGORITHMS).index(default_name)


def strategy_params(name, key):
    """Number/select inputs for exactly the selected strategy's parameters.

    Seeded with the class DEFAULTS, overlaid with the production config when this
    is the production strategy, so the dashboard runs the validated system by default.
    """
    seed = dict(ALGORITHMS[name].DEFAULTS)
    if name == DEFAULT_BUY:
        seed.update(DEFAULT_CONFIG)
    config = {}
    for param, value in seed.items():
        widget_key = f"{key}:{name}:{param}"
        if isinstance(value, str):
            options = ["trailing", "structural", "target"]
            config[param] = st.selectbox(param, options, index=options.index(value), key=widget_key)
        elif isinstance(value, int):
            config[param] = int(st.number_input(param, value=value, step=1, key=widget_key))
        else:
            config[param] = float(st.number_input(param, value=float(value), step=0.05, format="%.4g", key=widget_key))
    return config


def render_sidebar():
    """Collect every run parameter and return it as a dict."""
    with st.sidebar:
        st.header("Configuration")
        mode = st.radio(
            "Mode", MODES,
            help="Single = one ticker with full charts. Batch = the strategy on each ticker "
                 "independently. Portfolio = ONE account holding many positions (the realistic "
                 "research system). Scan today = which stocks fire a BUY on the latest bar.",
        )

        ticker, tickers, scan_scope = "AAPL", [], "sp500_ndx"
        as_of = pd.Timestamp.today().normalize()
        if mode == "Scan today":
            scope_label = st.selectbox("Universe to scan", list(SCAN_SCOPES), index=0)
            scan_scope = SCAN_SCOPES[scope_label]
            as_of = st.date_input("Scan as of", value=pd.Timestamp.today().normalize(),
                                  help="Which day's close to scan. Defaults to today.")
            st.caption("First run downloads data for the whole universe; repeat runs are cached.")
        elif mode == "Single stock":
            ticker_choice = st.selectbox("Ticker", PRESET_TICKERS, index=0)
            ticker = (st.text_input("Custom ticker", value="AAPL").strip().upper()
                      if ticker_choice == "Custom…" else ticker_choice)
        elif mode == "Portfolio backtest":
            scope_label = st.selectbox("Universe", list(SCAN_SCOPES), index=2)
            scan_scope = SCAN_SCOPES[scope_label]
        else:
            selected = st.multiselect("Universe", DEFAULT_UNIVERSE, default=DEFAULT_UNIVERSE,
                                      help="Pick from the default universe, and/or add more below.")
            extra_raw = st.text_area("Extra tickers (comma / space / newline separated)", value="",
                                     placeholder="e.g. ORCL, QCOM, T")
            tickers = selected + extra_raw.replace(",", " ").split()
            st.caption(f"{len(tickers)} ticker(s) queued for the scan.")

        portfolio_mode = mode == "Portfolio backtest"
        start_date = st.date_input("Start date", value=pd.to_datetime("2008-01-01" if portfolio_mode else "2018-01-01"))
        end_date = st.date_input("End date", value=pd.Timestamp.today().normalize())
        interval = "1d"
        if mode in ("Single stock", "Batch scan"):
            interval_label = st.selectbox(
                "Candle interval", list(INTERVAL_OPTIONS), index=1,
                help="Hourly only has ~730 days of history on Yahoo — use a recent date range for it.")
            interval = INTERVAL_OPTIONS[interval_label]
            if interval == "1h":
                st.warning("Hourly data is limited to ~the last 730 days. Pick a recent date range.")

        starting_capital = st.number_input("Starting capital ($)", min_value=100.0,
                                           value=100_000.0 if portfolio_mode else 10_000.0, step=1_000.0)

        algo_names = list(ALGORITHMS)
        buy_name = st.selectbox("Buy strategy", algo_names, index=_algo_index(DEFAULT_BUY))
        with st.expander("Buy strategy parameters"):
            buy_config = strategy_params(buy_name, "buy")
        sell_name, sell_config = buy_name, buy_config
        if mode != "Scan today":
            sell_choice = st.selectbox("Sell strategy", [SAME_AS_BUY] + algo_names, index=0)
            if sell_choice != SAME_AS_BUY:
                sell_name = sell_choice
                with st.expander("Sell strategy parameters"):
                    sell_config = strategy_params(sell_name, "sell")

        st.subheader("Test toggles")
        stop_mode = st.selectbox("Stop-loss mode", ["widest", "tightest"],
                                 index=0 if DEFAULT_STOP_MODE == "widest" else 1,
                                 help="widest = most room (production); tightest = smallest loss.")
        sizing_mode, fixed_fraction, max_positions, cost_bps = "risk_based", 0.95, TARGET_POSITIONS, 10.0
        if portfolio_mode:
            max_positions = int(st.number_input("Max positions", 1, 100, TARGET_POSITIONS))
            cost_bps = float(st.number_input("Cost (bps per side)", 0.0, 100.0, 10.0, 1.0))
        else:
            sizing_mode = st.selectbox("Position sizing", ["risk_based", "all_in", "fixed_fraction"],
                                       help="risk_based needs a strategy that defines a stop.")
            fixed_fraction = st.slider("Equity fraction % (fixed_fraction)", 10, 100, 95, 5) / 100.0
        risk_pct = st.slider("Risk % per trade (risk_based)", 0.1, 5.0, 1.0, 0.1) / 100.0
        fill_mode = st.selectbox("Fill timing", ["next_open", "close"],
                                 help="next_open = decide at the close, fill at the next open (realistic).")

        use_cache = st.checkbox("Use local price cache", value=True)
        run_clicked = st.button(RUN_LABELS[mode], type="primary", use_container_width=True)

    return {
        "mode": mode, "ticker": ticker, "tickers": tickers, "scan_scope": scan_scope,
        "as_of": str(as_of), "start_date": str(start_date), "end_date": str(end_date),
        "interval": interval, "starting_capital": starting_capital,
        "buy_name": buy_name, "buy_config": buy_config, "sell_name": sell_name, "sell_config": sell_config,
        "stop_mode": stop_mode, "sizing_mode": sizing_mode, "risk_pct": risk_pct,
        "fixed_fraction": fixed_fraction, "fill_mode": fill_mode, "max_positions": max_positions,
        "cost_bps": cost_bps, "use_cache": use_cache, "run_clicked": run_clicked,
    }


def build_algorithms(params):
    """(buy, sell) instances; the same instance when the sell side is the buy strategy."""
    buy = build_algorithm(params["buy_name"], params["buy_config"])
    same = params["sell_name"] == params["buy_name"] and params["sell_config"] == params["buy_config"]
    return buy, buy if same else build_algorithm(params["sell_name"], params["sell_config"])


def execute_run(params):
    """Build the algorithms, run the simulation, and stash results in session state."""
    buy_algo, sell_algo = build_algorithms(params)
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
    buy_algo, sell_algo = build_algorithms(params)
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
    buy_algo = build_algorithm(params["buy_name"], params["buy_config"])
    hits, errors = scan_for_buys(
        tickers, buy_algo, as_of=params["as_of"],
        interval=params["interval"], use_cache=params["use_cache"],
    )
    st.session_state["result_kind"] = "scan"
    st.session_state["scan_hits"] = hits
    st.session_state["scan_errors"] = errors
    st.session_state["scan_universe_size"] = len(tickers)
    st.session_state["params"] = params


def execute_portfolio(params):
    """Backtest ONE shared account over a universe (the research system) + benchmarks."""
    tickers = universe.get_universe(params["scan_scope"], use_cache=params["use_cache"])
    if params["use_cache"]:
        prefetch(tickers + ["SPY"], params["start_date"], params["end_date"])
    frames, failed = {}, []
    for ticker in tickers:
        try:
            frames[ticker] = fetch_data(ticker, params["start_date"], params["end_date"], use_cache=params["use_cache"])
        except PER_TICKER_ERRORS as exc:
            failed.append(f"{ticker} ({type(exc).__name__})")
    config = PortfolioConfig(
        starting_capital=params["starting_capital"], max_positions=params["max_positions"],
        risk_pct=params["risk_pct"], cost_bps=params["cost_bps"], fill_mode=params["fill_mode"],
        stop_mode=params["stop_mode"])
    buy_algo, sell_algo = build_algorithms(params)
    result = run_portfolio(frames, buy_algo, sell_algo, config)
    spy = fetch_data("SPY", params["start_date"], params["end_date"], use_cache=params["use_cache"])["Close"]
    benchmarks = {
        "Equal-weight buy & hold": buy_and_hold_portfolio({t: df["Close"] for t, df in frames.items()}, config),
        "SPY buy & hold": single_asset_benchmark(spy, config),
    }
    st.session_state.update({"result_kind": "portfolio", "params": params, "portfolio_result": result,
                             "portfolio_benchmarks": benchmarks, "portfolio_failed": failed,
                             "portfolio_size": len(frames)})


def render_portfolio_results():
    params = st.session_state["params"]
    result = st.session_state["portfolio_result"]
    benchmarks = st.session_state["portfolio_benchmarks"]
    m = result.metrics
    st.subheader(f"Portfolio — {params['buy_name']} · {st.session_state['portfolio_size']} stocks · "
                 f"max {params['max_positions']} positions · {params['fill_mode']} fills")
    cols = st.columns(5)
    cols[0].metric("CAGR", f"{m['cagr'] * 100:.1f}%")
    cols[1].metric("Max drawdown", f"{m['max_dd'] * 100:.1f}%")
    cols[2].metric("Sharpe", f"{m['sharpe']:.2f}")
    cols[3].metric("Final equity", f"${m['final_equity']:,.0f}")
    cols[4].metric("Trades", f"{m['n_trades']}", help=f"win rate {m['win_rate'] * 100:.0f}%, "
                                                         f"avg hold {m['avg_hold_bars']:.0f} bars")
    fig = go.Figure(go.Scatter(x=result.equity.index, y=result.equity, name="Strategy", line=dict(width=2.5)))
    rows = [{"system": "Strategy", **{k: m[k] for k in ("cagr", "max_dd", "sharpe", "calmar")}}]
    for name, equity in benchmarks.items():
        equity = equity[equity.index >= result.equity.index[0]]
        fig.add_trace(go.Scatter(x=equity.index, y=equity, name=name, line=dict(width=1.3)))
        bench = equity_metrics(equity)
        rows.append({"system": name, **{k: bench[k] for k in ("cagr", "max_dd", "sharpe", "calmar")}})
    fig.update_layout(height=420, yaxis_type="log", margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)
    table = pd.DataFrame(rows)
    table["cagr"] = (table["cagr"] * 100).round(2)
    table["max_dd"] = (table["max_dd"] * 100).round(1)
    st.dataframe(table.round(2), use_container_width=True, hide_index=True)
    trades = pd.DataFrame([{**t.__dict__, "ret_%": round(t.ret * 100, 2), "pnl": round(t.pnl, 2)}
                           for t in result.trades])
    if not trades.empty:
        st.markdown("**Trades**")
        st.dataframe(trades.sort_values("entry_date", ascending=False), use_container_width=True, hide_index=True)
    if st.session_state["portfolio_failed"]:
        st.caption("Skipped (no usable data): " + ", ".join(st.session_state["portfolio_failed"]))


def build_price_chart(df, trades, config):
    """Candlestick + the strategy's own overlay (Bollinger Bands or its trend MA) + BUY/SELL markers."""
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
            name="Price",
        )
    )
    band_line = dict(width=1)
    if "bb_period" in config:
        middle, upper, lower = indicators.bollinger_bands(df["Close"], config["bb_period"], config["bb_std"])
        fig.add_trace(go.Scatter(x=df.index, y=upper, name="Upper BB", line=dict(color="#8fa8ff", **band_line)))
        fig.add_trace(go.Scatter(x=df.index, y=middle, name="Middle BB", line=dict(color="#aaaaaa", dash="dot", **band_line)))
        fig.add_trace(go.Scatter(x=df.index, y=lower, name="Lower BB", line=dict(color="#8fa8ff", **band_line)))
    for key in ("trend_ma", "exit_ma", "ma_period", "trend_sma"):
        if key in config:
            fig.add_trace(go.Scatter(x=df.index, y=indicators.sma(df["Close"], config[key]),
                                     name=f"SMA {config[key]} ({key})", line=dict(color="#e39b3c", **band_line)))

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
        build_price_chart(df, trades, params["buy_config"]),
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
            build_price_chart(chosen_df, trades, params["buy_config"]),
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
    cols[3].metric("Stop mode", params["stop_mode"])

    if hits.empty:
        st.info("No stock fires the entry signal on this bar. Try another date or universe.")
    else:
        st.markdown("**Stocks to consider buying** (strongest score first)")
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
        algo = build_algorithm(params["buy_name"], params["buy_config"])
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
    elif params["mode"] == "Portfolio backtest":
        with st.spinner("Backtesting one shared account over the universe… (first run downloads data)"):
            execute_portfolio(params)
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
    elif kind == "portfolio":
        render_portfolio_results()
    else:
        render_results()
else:
    st.info("Configure a run in the sidebar and click **Run**.")

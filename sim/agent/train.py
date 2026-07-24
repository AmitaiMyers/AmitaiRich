import os
import random
import torch
import numpy as np
from sim import store
from sim.datasource import TICKERS
from sim.agent.env import TradingEnv
from sim.agent.dqn_agent import DQNAgent


def _make_session_sampler(source: str):
    """Return (sampler, description). sampler() -> (session_data, label).

    'stock'  : real Yahoo day-sessions (synthetic book, real OHLCV).
    'crypto' : real Binance recordings (fully real data). Both feed the same
               TradingEnv, which appends indicator features to the state.
    """
    if source == "crypto":
        recs = store.crypto_recordings()
        assert recs, "No crypto recordings. Run 'python -m sim.crypto_record' first."
        pool = [(sym, r["recid"]) for r in recs for sym in r["symbols"]]

        def sample():
            sym, recid = random.choice(pool)
            return store.load_crypto_session(sym, recid), f"{sym} ({recid})"
        return sample, f"{len(pool)} crypto symbol-sessions across {len(recs)} recording(s)"

    dates = store.available_dates()
    assert len(dates) > 0, "No cached data found. Run 'python -m sim.ingest' to fetch market data first."
    tickers = list(TICKERS.keys())

    def sample():
        ticker, date_str = random.choice(tickers), random.choice(dates)
        assert store.is_cached(ticker, date_str), f"Session cache missing for {ticker} on {date_str}."
        return store.load_session(ticker, date_str), f"{ticker} ({date_str})"
    return sample, f"{len(dates)} trading days x {len(tickers)} tickers"


def train_dqn(episodes: int = 500, lookback: int = 60, batch_size: int = 64, source: str = "stock"):
    sample_session, pool_desc = _make_session_sampler(source)

    # State = lookback window of normalized prices + cash + position + indicator features
    # (Bollinger %B/bandwidth, ADX, OBV, relative volume — see TradingEnv).
    state_dim = lookback + 2 + TradingEnv.N_INDICATOR_FEATURES
    action_dim = 3  # 0: Hold, 1: Buy Max, 2: Sell Max

    agent = DQNAgent(state_dim=state_dim, action_dim=action_dim)

    print(f"Starting Training: {episodes} episodes | source='{source}' | {pool_desc}.")

    for episode in range(1, episodes + 1):
        # Sample a random session to prevent overfitting to one asset's price curve
        session_data, label = sample_session()

        env = TradingEnv(session_data, lookback=lookback)
        state = env.reset()

        done = False
        final_equity = 100000.0

        while not done:
            action = agent.select_action(state)
            next_state, reward, done, equity = env.step(action)
            final_equity = equity

            # Store the transition in the replay buffer
            if next_state is not None:
                agent.memory.push(state, action, reward, next_state, done)

            # Train the network on a batch of past experiences
            agent.train_step(batch_size)

            state = next_state

        # Crucial DQN mechanics to run at the end of every episode
        agent.update_target_network()
        agent.decay_epsilon()

        # Progress reporting
        pnl = final_equity - 100000.0
        print(f"Episode {episode:03d}/{episodes} | {label} | "
              f"P&L: ${pnl:+8.2f} | Eq: ${final_equity:.2f} | EPS: {agent.epsilon:.3f}")

    # ==========================================
    # BUG FIX: Explicitly save the model weights
    # ==========================================
    os.makedirs("models", exist_ok=True)
    save_path = os.path.join("models", "dqn_trading_model.pth")
    torch.save(agent.policy_net.state_dict(), save_path)
    print(f"\nTraining complete. Model weights saved to: {save_path}")


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Train the DQN trading agent.")
    p.add_argument("--source", choices=["stock", "crypto"], default="stock",
                   help="Train on real Yahoo stock sessions or real Binance crypto recordings.")
    p.add_argument("--episodes", type=int, default=500)
    p.add_argument("--lookback", type=int, default=60)
    p.add_argument("--batch-size", type=int, default=64)
    args = p.parse_args(argv)
    train_dqn(episodes=args.episodes, lookback=args.lookback, batch_size=args.batch_size, source=args.source)


if __name__ == "__main__":
    main()
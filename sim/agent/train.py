import os
import random
import torch
import numpy as np
from sim import store
from sim.datasource import TICKERS
from sim.agent.env import TradingEnv
from sim.agent.dqn_agent import DQNAgent


def train_dqn(episodes: int = 500, lookback: int = 60, batch_size: int = 64):
    # Retrieve available dates from the JSON cache explicitly
    dates = store.available_dates()

    # Fail Fast: Stop execution if no data has been ingested yet
    assert len(dates) > 0, "No cached data found. Run 'python -m sim.ingest' to fetch market data first."

    tickers = list(TICKERS.keys())

    # The state array contains the lookback window of normalized prices PLUS current cash and position
    state_dim = lookback + 2
    action_dim = 3  # 0: Hold, 1: Buy Max, 2: Sell Max

    agent = DQNAgent(state_dim=state_dim, action_dim=action_dim)

    print(f"Starting Training: {episodes} episodes over {len(dates)} available trading days.")

    for episode in range(1, episodes + 1):
        # Sample a random ticker and date to prevent overfitting to a single asset's price curve
        ticker = random.choice(tickers)
        date_str = random.choice(dates)

        # Fail Fast: Ensure the exact session exists before loading
        assert store.is_cached(ticker, date_str), f"Session cache missing for {ticker} on {date_str}."
        session_data = store.load_session(ticker, date_str)

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
        print(f"Episode {episode:03d}/{episodes} | {ticker} ({date_str}) | "
              f"P&L: ${pnl:+8.2f} | Eq: ${final_equity:.2f} | EPS: {agent.epsilon:.3f}")

    # ==========================================
    # BUG FIX: Explicitly save the model weights
    # ==========================================
    os.makedirs("models", exist_ok=True)
    save_path = os.path.join("models", "dqn_trading_model.pth")
    torch.save(agent.policy_net.state_dict(), save_path)
    print(f"\nTraining complete. Model weights saved to: {save_path}")


if __name__ == "__main__":
    train_dqn()
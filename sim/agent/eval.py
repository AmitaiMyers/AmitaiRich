import os
import torch
import random
from sim import store
from sim.datasource import TICKERS
from sim.env import TradingEnv
from sim.dqn_agent import DQNAgent


def evaluate_model(model_path: str = "models/dqn_trading_model.pth", lookback: int = 60):
    # Fail Fast: Ensure the model actually exists before trying to load it
    assert os.path.exists(model_path), f"Model file not found at {model_path}. You must complete training first."

    dates = store.available_dates()
    assert len(dates) > 0, "No cached data found. Run 'python -m sim.ingest' to fetch market data first."

    state_dim = lookback + 2
    action_dim = 3

    # Initialize agent but force epsilon to 0.0 for pure exploitation (no random guessing)
    agent = DQNAgent(state_dim=state_dim, action_dim=action_dim, epsilon_start=0.0, epsilon_min=0.0)

    # Load the saved model weights
    # map_location ensures it loads correctly whether you trained on GPU or CPU
    agent.policy_net.load_state_dict(torch.load(model_path, map_location=agent.device, weights_only=True))
    agent.policy_net.eval()  # Set network to evaluation mode

    # Pick a random cached session to test the model on unseen data
    ticker = random.choice(list(TICKERS.keys()))
    date_str = random.choice(dates)

    assert store.is_cached(ticker, date_str), f"Session cache missing for {ticker} on {date_str}."
    session_data = store.load_session(ticker, date_str)

    env = TradingEnv(session_data, lookback=lookback)
    state = env.reset()

    done = False
    final_equity = 100000.0
    action_counts = {0: 0, 1: 0, 2: 0}

    print(f"--- Starting Evaluation ---")
    print(f"Target: {ticker} on {date_str}")
    print(f"Model: {model_path}")
    print(f"---------------------------\n")

    while not done:
        # Agent will purely exploit the learned Q-values
        action = agent.select_action(state)
        action_counts[action] += 1

        next_state, reward, done, equity = env.step(action)
        final_equity = equity
        state = next_state

    pnl = final_equity - 100000.0

    print(f"Evaluation Complete!")
    print(f"Final Equity: ${final_equity:.2f} | P&L: ${pnl:+8.2f}")
    print(f"Actions Taken -> Hold: {action_counts[0]}, Buy: {action_counts[1]}, Sell: {action_counts[2]}")


if __name__ == "__main__":
    evaluate_model()
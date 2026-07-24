import os
import torch
import random
from sim.agent.env import TradingEnv
from sim.agent.dqn_agent import DQNAgent
from sim.agent.train import _make_session_sampler


def evaluate_model(model_path: str = "models/dqn_trading_model.pth", lookback: int = 60, source: str = "stock"):
    # Fail Fast: Ensure the model actually exists before trying to load it
    assert os.path.exists(model_path), f"Model file not found at {model_path}. You must complete training first."

    sample_session, _ = _make_session_sampler(source)

    state_dim = lookback + 2 + TradingEnv.N_INDICATOR_FEATURES
    action_dim = 3

    # Initialize agent but force epsilon to 0.0 for pure exploitation (no random guessing)
    agent = DQNAgent(state_dim=state_dim, action_dim=action_dim, epsilon_start=0.0, epsilon_min=0.0)

    # Load the saved model weights
    # map_location ensures it loads correctly whether you trained on GPU or CPU
    agent.policy_net.load_state_dict(torch.load(model_path, map_location=agent.device, weights_only=True))
    agent.policy_net.eval()  # Set network to evaluation mode

    # Pick a random cached session to test the model on
    session_data, label = sample_session()

    env = TradingEnv(session_data, lookback=lookback)
    state = env.reset()

    done = False
    final_equity = 100000.0
    action_counts = {0: 0, 1: 0, 2: 0}

    print(f"--- Starting Evaluation ---")
    print(f"Target: {label}")
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


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Evaluate a trained DQN trading agent.")
    p.add_argument("--source", choices=["stock", "crypto"], default="stock")
    p.add_argument("--model", default="models/dqn_trading_model.pth")
    p.add_argument("--lookback", type=int, default=60)
    args = p.parse_args(argv)
    evaluate_model(model_path=args.model, lookback=args.lookback, source=args.source)


if __name__ == "__main__":
    main()
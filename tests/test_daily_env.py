"""DQN daily environment: transaction costs are charged on every fill."""

import unittest

import numpy as np

from sim.agent.daily_env import START_CASH, DailyTradingEnv


class DailyEnvCostTest(unittest.TestCase):
    def _round_trip(self, cost_bps):
        closes = np.array([100.0, 100.0, 100.0, 100.0])
        env = DailyTradingEnv("X", np.zeros((4, 2)), closes, cost_bps=cost_bps)
        env.reset()
        env.step(1)              # buy at 100
        _, _, _, equity = env.step(2)  # sell at 100
        return equity

    def test_flat_round_trip_costs_exactly_two_sides(self):
        self.assertAlmostEqual(self._round_trip(0.0), START_CASH)
        expected = START_CASH / (1 + 0.001) * (1 - 0.001)
        self.assertAlmostEqual(self._round_trip(10.0), expected)

    def test_costs_make_churning_unprofitable(self):
        closes = np.full(30, 50.0)
        env = DailyTradingEnv("X", np.zeros((30, 2)), closes, cost_bps=10.0)
        env.reset()
        done, total_reward = False, 0.0
        action = 1
        while not done:
            _, reward, done, equity = env.step(action)
            total_reward += reward
            action = 2 if action == 1 else 1
        self.assertLess(equity, START_CASH)
        self.assertLess(total_reward, 0.0)


if __name__ == "__main__":
    unittest.main()

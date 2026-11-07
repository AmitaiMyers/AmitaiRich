"""Daily trading environment for the DQN agent.

Consumes ONE ticker's daily feature matrix + close series (from the dataset) and
steps day by day. Unlike the intraday `TradingEnv`, the state is the full stationary
indicator vector at the current day plus lightweight position context — so the agent
learns from the indicators directly.

State  : [ <all daily indicator features>, position_flag, unrealized_return ]
Actions: 0 = Hold, 1 = Buy (go long, all-in), 2 = Sell (go flat)
Reward : log return of equity from this day to the next (stationary across tickers).
"""

import numpy as np

START_CASH = 100000.0


class DailyTradingEnv:
    """`window=1` -> state is the current day's features (MLP agent).
    `window>1` -> state is the last `window` days flattened (sequence agent).
    """

    def __init__(self, ticker, features, closes, window: int = 1):
        assert features.ndim == 2, "features must be 2D [T, F]"
        assert len(features) == len(closes), "features/closes length mismatch"
        assert window >= 1, "window must be >= 1"
        assert len(closes) > window + 1, "session too short for the window"
        self.ticker = ticker
        self.features = np.asarray(features, dtype=np.float32)
        self.closes = np.asarray(closes, dtype=np.float64)
        self.n = len(closes)
        self.window = window
        self.reset()

    @property
    def feature_dim(self):
        return self.features.shape[1]

    @property
    def state_dim(self):
        return self.window * self.feature_dim + 2  # window of features + position_flag + unrealized

    def reset(self):
        self.t = self.window - 1   # need `window` days of history for the first state
        self.cash = START_CASH
        self.shares = 0.0
        self.entry = 0.0
        return self._state()

    def _equity(self, t):
        return self.cash + self.shares * self.closes[t]

    def _state(self):
        pos_flag = 1.0 if self.shares > 0 else 0.0
        unreal = (self.closes[self.t] / self.entry - 1.0) if self.shares > 0 and self.entry > 0 else 0.0
        win = self.features[self.t - self.window + 1: self.t + 1]   # [window, F]
        return np.concatenate([win.reshape(-1), [pos_flag, unreal]]).astype(np.float32)

    def step(self, action: int):
        assert action in (0, 1, 2), f"Invalid action {action} (0=Hold, 1=Buy, 2=Sell)."
        price = self.closes[self.t]
        equity_prev = self._equity(self.t)

        if action == 1 and self.shares == 0.0:
            self.shares = self.cash / price   # all-in (fractional shares ok in sim)
            self.entry = price
            self.cash = 0.0
        elif action == 2 and self.shares > 0.0:
            self.cash = self.shares * price
            self.shares = 0.0
            self.entry = 0.0

        self.t += 1
        done = self.t >= self.n - 1
        equity_now = self._equity(min(self.t, self.n - 1))
        # log return keeps the reward scale stable across very differently-priced tickers
        reward = float(np.log(equity_now / equity_prev)) if equity_prev > 0 and equity_now > 0 else 0.0
        return (self._state() if not done else None), reward, done, equity_now

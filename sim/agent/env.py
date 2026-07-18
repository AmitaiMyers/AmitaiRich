import numpy as np


class TradingEnv:
    def __init__(self, session_data: dict, lookback: int = 60):
        # Fail Fast: Ensure required keys exist directly
        self.ticker = session_data["ticker"]
        self.prices = session_data["prices"]
        self.vols = session_data["vols"]

        assert isinstance(self.prices, list), "Prices must be a list"
        assert len(self.prices) > lookback, "Session data shorter than lookback window"

        self.lookback = lookback
        self.current_step = lookback
        self.cash = 100000.0  # Simulator default starting cash
        self.position = 0

    def reset(self):
        self.current_step = self.lookback
        self.cash = 100000.0
        self.position = 0
        return self._get_state()

    def step(self, action: int):
        # Explicit validation
        assert action in [0, 1, 2], f"Invalid action {action}. Must be 0 (Hold), 1 (Buy), or 2 (Sell)."

        current_price = self.prices[self.current_step]
        prev_equity = self.cash + (self.position * self.prices[self.current_step - 1])

        self._execute_trade(action, current_price)

        # Advance time
        self.current_step += 1
        done = self.current_step >= len(self.prices)

        # Calculate new state and rewards
        current_equity = self.cash + (self.position * self.prices[min(self.current_step, len(self.prices) - 1)])
        reward = current_equity - prev_equity

        return self._get_state() if not done else None, reward, done, current_equity

    def _execute_trade(self, action: int, current_price: float):
        # 0 = Hold, 1 = Buy Max, 2 = Sell Max
        if action == 1 and self.cash > 0:
            # Buy as many whole shares as possible
            qty = int(self.cash // current_price)
            assert qty >= 0, "Calculated negative quantity"
            self.position += qty
            self.cash -= qty * current_price

        elif action == 2 and self.position > 0:
            # Liquidate position
            self.cash += self.position * current_price
            self.position = 0

    def _get_state(self):
        # Extract the sliding window
        window_start = self.current_step - self.lookback
        price_window = self.prices[window_start:self.current_step]

        # Normalize: percentage return from the first price in the window
        base_price = price_window[0]
        assert base_price > 0, "Base price is zero or negative, cannot normalize."

        normalized_prices = [(p - base_price) / base_price for p in price_window]

        # Build the state vector explicitly
        state = np.array(normalized_prices + [self.cash, self.position], dtype=np.float32)
        return state
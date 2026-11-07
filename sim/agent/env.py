import numpy as np
import pandas as pd

from indicators import bollinger_bands, adx, on_balance_volume


class TradingEnv:
    # Indicator features appended to the state when use_indicators=True:
    #   %B, Bollinger bandwidth, ADX/100, normalized OBV, volume vs session average.
    N_INDICATOR_FEATURES = 5

    def __init__(self, session_data: dict, lookback: int = 60, use_indicators: bool = True):
        # Fail Fast: Ensure required keys exist directly. Sessions come in two
        # shapes — stock ("ticker") and crypto ("symbol") — both carry prices/vols.
        self.ticker = session_data["ticker"] if "ticker" in session_data else session_data["symbol"]
        self.prices = session_data["prices"]
        self.vols = session_data["vols"]

        assert isinstance(self.prices, list), "Prices must be a list"
        assert len(self.prices) > lookback, "Session data shorter than lookback window"

        self.lookback = lookback
        self.use_indicators = use_indicators
        self.current_step = lookback
        self.cash = 100000.0  # Simulator default starting cash
        self.position = 0

        self._precompute_indicators()

    @property
    def state_size(self) -> int:
        """Length of the state vector (lookback prices + cash + position + indicators)."""
        return self.lookback + 2 + (self.N_INDICATOR_FEATURES if self.use_indicators else 0)

    def _precompute_indicators(self):
        """Compute indicator series once over the whole session (indexed by step).

        Same indicators the UI shows (Bollinger 14/2, ADX 14, OBV) so the agent
        trains on exactly what the trader sees. Computed on the per-second series,
        so periods are in steps. Warmup produces NaN (handled in `_get_state`).
        """
        close = pd.Series(self.prices, dtype=float)
        vol = pd.Series(self.vols, dtype=float)

        mid, upper, lower = bollinger_bands(close, period=14, num_std=2.0)
        band = upper - lower
        self._pct_b = ((close - lower) / band.where(band != 0)).to_numpy()
        self._bandwidth = (band / mid.where(mid != 0)).to_numpy()

        # tick series has no separate highs/lows -> DM derives from close moves
        adx_series, _, _ = adx(close, close, close, period=14)
        self._adx = (adx_series / 100.0).to_numpy()

        obv_series = on_balance_volume(close, vol)
        total_vol = float(vol.abs().sum()) or 1.0
        self._obv = (obv_series / total_vol).to_numpy()

        mean_vol = float(vol.mean()) or 1.0
        self._vol_rel = (vol / mean_vol).to_numpy()

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

    def _indicator_features(self):
        """The 5 indicator values at the current step, NaN warmup mapped to 0.0.

        current_step starts at `lookback` (>= 60), well past the 14-bar warmup, so
        in practice these are always finite — the guard only covers a tiny-lookback
        misconfiguration and never repairs real market data.
        """
        i = self.current_step
        feats = [self._pct_b[i], self._bandwidth[i], self._adx[i], self._obv[i], self._vol_rel[i]]
        return [float(f) if np.isfinite(f) else 0.0 for f in feats]

    def _get_state(self):
        # Extract the sliding window
        window_start = self.current_step - self.lookback
        price_window = self.prices[window_start:self.current_step]

        # Normalize: percentage return from the first price in the window
        base_price = price_window[0]
        assert base_price > 0, "Base price is zero or negative, cannot normalize."

        normalized_prices = [(p - base_price) / base_price for p in price_window]

        # Build the state vector explicitly
        state_values = normalized_prices + [self.cash, self.position]
        if self.use_indicators:
            state_values = state_values + self._indicator_features()
        return np.array(state_values, dtype=np.float32)

import random
from collections import deque
import numpy as np
import torch
import torch.nn as nn


class ReplayBuffer:
    def __init__(self, capacity: int):
        assert capacity > 0, "Buffer capacity must be greater than 0"
        self.buffer = deque(maxlen=capacity)

    def push(self, state: np.ndarray, action: int, reward: float, next_state: np.ndarray, done: bool):
        # Fail fast: ensure we are storing flat arrays
        assert state.ndim == 1, "State must be a 1D array"
        assert next_state.ndim == 1, "Next state must be a 1D array"
        self.buffer.append((state, action, reward, next_state, done))

    def sample(self, batch_size: int):
        assert len(self.buffer) >= batch_size, "Not enough samples in buffer to draw a batch"

        batch = random.sample(self.buffer, batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)

        # Explicitly convert to tensors for robust PyTorch execution
        return (
            torch.tensor(np.array(states), dtype=torch.float32),
            torch.tensor(actions, dtype=torch.long),
            torch.tensor(rewards, dtype=torch.float32),
            torch.tensor(np.array(next_states), dtype=torch.float32),
            torch.tensor(dones, dtype=torch.float32)
        )

    def __len__(self):
        return len(self.buffer)


class TradingDQN(nn.Module):
    def __init__(self, input_dim: int, output_dim: int):
        super(TradingDQN, self).__init__()
        assert input_dim > 0 and output_dim > 0, "Dimensions must be strictly positive"

        # RIPER: Explicit sequential flow, no clever tricks
        self.network = nn.Sequential(
            nn.Linear(input_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, output_dim)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.network(x)
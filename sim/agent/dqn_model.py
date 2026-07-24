import math
import random
from collections import deque

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


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

        return (
            torch.tensor(np.array(states), dtype=torch.float32),
            torch.tensor(actions, dtype=torch.long),
            torch.tensor(rewards, dtype=torch.float32),
            torch.tensor(np.array(next_states), dtype=torch.float32),
            torch.tensor(dones, dtype=torch.float32),
        )

    def __len__(self):
        return len(self.buffer)


class NoisyLinear(nn.Module):
    """Factorized-Gaussian NoisyNet linear layer (Fortunato et al., 2017).

    Learns a mean weight AND a noise scale; exploration comes from sampling weight
    noise, so the agent learns *where* to explore instead of acting uniformly at
    random (ε-greedy). In eval() mode the noise is dropped -> deterministic (mean)
    output, which is exactly what we want for greedy validation.
    """

    def __init__(self, in_features, out_features, sigma_init=0.5):
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.weight_mu = nn.Parameter(torch.empty(out_features, in_features))
        self.weight_sigma = nn.Parameter(torch.empty(out_features, in_features))
        self.register_buffer("weight_epsilon", torch.empty(out_features, in_features))
        self.bias_mu = nn.Parameter(torch.empty(out_features))
        self.bias_sigma = nn.Parameter(torch.empty(out_features))
        self.register_buffer("bias_epsilon", torch.empty(out_features))
        self.sigma_init = sigma_init
        self.reset_parameters()
        self.reset_noise()

    def reset_parameters(self):
        mu_range = 1.0 / math.sqrt(self.in_features)
        self.weight_mu.data.uniform_(-mu_range, mu_range)
        self.weight_sigma.data.fill_(self.sigma_init / math.sqrt(self.in_features))
        self.bias_mu.data.uniform_(-mu_range, mu_range)
        self.bias_sigma.data.fill_(self.sigma_init / math.sqrt(self.out_features))

    @staticmethod
    def _scale_noise(size):
        x = torch.randn(size)
        return x.sign().mul_(x.abs().sqrt_())

    def reset_noise(self):
        eps_in = self._scale_noise(self.in_features)
        eps_out = self._scale_noise(self.out_features)
        self.weight_epsilon.copy_(eps_out.outer(eps_in))
        self.bias_epsilon.copy_(eps_out)

    def forward(self, x):
        if self.training:
            weight = self.weight_mu + self.weight_sigma * self.weight_epsilon
            bias = self.bias_mu + self.bias_sigma * self.bias_epsilon
        else:
            weight, bias = self.weight_mu, self.bias_mu
        return F.linear(x, weight, bias)


class _ResidualBlock(nn.Module):
    """Linear -> LayerNorm -> ReLU -> Dropout, with a skip connection when the
    input and output widths match (so gradients flow cleanly through the stack)."""

    def __init__(self, in_dim, out_dim, dropout):
        super().__init__()
        self.fc = nn.Linear(in_dim, out_dim)
        self.norm = nn.LayerNorm(out_dim)
        self.drop = nn.Dropout(dropout)
        self.residual = in_dim == out_dim

    def forward(self, x):
        y = self.drop(F.relu(self.norm(self.fc(x))))
        return x + y if self.residual else y


class DuelingDQN(nn.Module):
    """Dueling Double-DQN-ready network with a residual trunk and NoisyNet heads.

    Q(s,a) = V(s) + (A(s,a) - mean_a A(s,a)). The dueling decomposition lets the
    net learn state value independently of the action advantages — valuable here
    because most days "hold" is correct, so V(s) carries most of the signal.
    """

    def __init__(self, input_dim: int, output_dim: int, hidden=(256, 256, 128),
                 dropout: float = 0.1, noisy: bool = True):
        super().__init__()
        assert input_dim > 0 and output_dim > 0, "Dimensions must be strictly positive"
        assert len(hidden) > 0, "Need at least one hidden layer"
        self.noisy = noisy

        blocks, prev = [], input_dim
        for h in hidden:
            blocks.append(_ResidualBlock(prev, h, dropout))
            prev = h
        self.trunk = nn.Sequential(*blocks)

        feat = prev
        head_hidden = max(64, feat // 2)
        Linear = NoisyLinear if noisy else nn.Linear
        self.value = nn.Sequential(Linear(feat, head_hidden), nn.ReLU(), Linear(head_hidden, 1))
        self.advantage = nn.Sequential(Linear(feat, head_hidden), nn.ReLU(), Linear(head_hidden, output_dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.trunk(x)
        value = self.value(features)
        advantage = self.advantage(features)
        return value + (advantage - advantage.mean(dim=1, keepdim=True))

    def reset_noise(self):
        """Resample NoisyNet noise (call each learning step / action selection)."""
        if not self.noisy:
            return
        for module in self.modules():
            if isinstance(module, NoisyLinear):
                module.reset_noise()


class SequenceDuelingDQN(nn.Module):
    """Dueling DQN whose trunk is a SEQUENCE encoder over the last `window` days.

    The flat state is [ window*feature_dim  ||  context_dim ] — the first part is a
    window of daily feature vectors (reshaped to [B, window, F] inside forward), the
    tail is position context. A GRU or Transformer encodes the window; its final
    representation is concatenated with the context and fed to dueling value/advantage
    heads. This lets the agent learn temporal structure the hand-crafted indicators
    don't capture, instead of seeing a single day in isolation.
    """

    def __init__(self, feature_dim, window, output_dim, context_dim=2, encoder="gru",
                 d_model=128, num_layers=2, nhead=4, dropout=0.1, noisy=True):
        super().__init__()
        assert feature_dim > 0 and window > 1, "sequence model needs window > 1"
        assert encoder in ("gru", "transformer"), f"unknown encoder {encoder!r}"
        self.feature_dim = feature_dim
        self.window = window
        self.context_dim = context_dim
        self.encoder_type = encoder
        self.noisy = noisy

        if encoder == "gru":
            self.rnn = nn.GRU(feature_dim, d_model, num_layers=num_layers,
                              batch_first=True, dropout=dropout if num_layers > 1 else 0.0)
        else:  # transformer
            self.input_proj = nn.Linear(feature_dim, d_model)
            self.pos = nn.Parameter(torch.zeros(1, window, d_model))   # learned positional encoding
            enc_layer = nn.TransformerEncoderLayer(
                d_model=d_model, nhead=nhead, dim_feedforward=d_model * 2,
                dropout=dropout, batch_first=True, activation="gelu")
            self.transformer = nn.TransformerEncoder(enc_layer, num_layers=num_layers)

        self.norm = nn.LayerNorm(d_model)
        feat = d_model + context_dim
        head_hidden = max(64, d_model // 2)
        Linear = NoisyLinear if noisy else nn.Linear
        self.value = nn.Sequential(Linear(feat, head_hidden), nn.ReLU(), Linear(head_hidden, 1))
        self.advantage = nn.Sequential(Linear(feat, head_hidden), nn.ReLU(), Linear(head_hidden, output_dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch = x.shape[0]
        seq_len = self.window * self.feature_dim
        seq = x[:, :seq_len].reshape(batch, self.window, self.feature_dim)
        ctx = x[:, seq_len:]
        if self.encoder_type == "gru":
            out, _ = self.rnn(seq)          # [B, window, d_model]
            encoded = out[:, -1, :]         # last day's hidden state
        else:
            h = self.input_proj(seq) + self.pos
            h = self.transformer(h)         # [B, window, d_model]
            encoded = h[:, -1, :]           # representation aligned to the current day
        encoded = self.norm(encoded)
        features = torch.cat([encoded, ctx], dim=1)
        value = self.value(features)
        advantage = self.advantage(features)
        return value + (advantage - advantage.mean(dim=1, keepdim=True))

    def reset_noise(self):
        if not self.noisy:
            return
        for module in self.modules():
            if isinstance(module, NoisyLinear):
                module.reset_noise()

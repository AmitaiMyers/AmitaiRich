import torch
import torch.optim as optim
import torch.nn.functional as F
import random
import numpy as np
from sim.agent.dqn_model import DuelingDQN, SequenceDuelingDQN, ReplayBuffer


class DQNAgent:
    def __init__(self, state_dim: int, action_dim: int, lr: float = 5e-4, gamma: float = 0.99,
                 epsilon_start: float = 1.0, epsilon_min: float = 0.05, epsilon_decay: float = 0.997,
                 hidden=(256, 256, 128), dropout: float = 0.1, buffer_size: int = 50000,
                 noisy: bool = True, arch: str = "mlp", feature_dim: int = None, window: int = 1,
                 d_model: int = 128, seq_layers: int = 2, nhead: int = 4, ff_mult: int = 2):
        assert state_dim > 0 and action_dim > 0, "Invalid dimensions"
        assert arch in ("mlp", "gru", "transformer"), f"unknown arch {arch!r}"

        self.state_dim = state_dim
        self.action_dim = action_dim
        self.hidden = tuple(hidden)
        self.dropout = dropout
        self.noisy = noisy          # NoisyNet exploration -> epsilon-greedy is only a fallback
        self.arch = arch
        self.feature_dim = feature_dim
        self.window = window
        self.d_model = d_model
        self.seq_layers = seq_layers
        self.nhead = nhead
        self.ff_mult = ff_mult
        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay

        # Determine device implicitly based on hardware availability
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.policy_net = self._build_net().to(self.device)
        self.target_net = self._build_net().to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()  # Target network does not learn directly (mean/no-noise)

        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=lr)
        self.memory = ReplayBuffer(capacity=buffer_size)

    def _build_net(self):
        """MLP dueling net, or a GRU/Transformer sequence encoder + dueling heads."""
        if self.arch == "mlp":
            return DuelingDQN(self.state_dim, self.action_dim, hidden=self.hidden,
                              dropout=self.dropout, noisy=self.noisy)
        assert self.feature_dim and self.window > 1, "sequence arch needs feature_dim and window > 1"
        context_dim = self.state_dim - self.window * self.feature_dim
        assert context_dim >= 0, "state_dim smaller than window*feature_dim"
        return SequenceDuelingDQN(
            self.feature_dim, self.window, self.action_dim, context_dim=context_dim,
            encoder=self.arch, d_model=self.d_model, num_layers=self.seq_layers,
            nhead=self.nhead, dropout=self.dropout, noisy=self.noisy, ff_mult=self.ff_mult)

    def select_action(self, state: np.ndarray) -> int:
        assert state.ndim == 1, "State must be 1D"

        # With NoisyNet, exploration is baked into the network's sampled weights
        # (resampled each step while training); in eval() the net is deterministic,
        # giving greedy validation. Without NoisyNet, fall back to epsilon-greedy.
        if not self.noisy and random.random() < self.epsilon:
            return random.randrange(self.action_dim)

        with torch.no_grad():
            if self.noisy and self.policy_net.training:
                self.policy_net.reset_noise()
            state_tensor = torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(self.device)
            q_values = self.policy_net(state_tensor)
            return q_values.argmax().item()

    def train_step(self, batch_size: int):
        if len(self.memory) < batch_size:
            return None  # not enough data to train yet

        states, actions, rewards, next_states, dones = self.memory.sample(batch_size)

        # Fresh NoisyNet noise for this gradient step (target stays deterministic/eval)
        if self.noisy:
            self.policy_net.reset_noise()

        states = states.to(self.device)
        actions = actions.to(self.device)
        rewards = rewards.to(self.device)
        next_states = next_states.to(self.device)
        dones = dones.to(self.device)

        # Current Q values
        q_values = self.policy_net(states)
        state_action_values = q_values.gather(1, actions.unsqueeze(1)).squeeze(1)

        # Double DQN: the ONLINE net picks the next action, the TARGET net scores it.
        # This decouples selection from evaluation and curbs Q-value overestimation.
        with torch.no_grad():
            next_actions = self.policy_net(next_states).argmax(1, keepdim=True)
            max_next_q_values = self.target_net(next_states).gather(1, next_actions).squeeze(1)

        # Compute the expected Q values (Bellman equation)
        expected_state_action_values = rewards + (self.gamma * max_next_q_values * (1 - dones))

        # Compute Huber loss
        loss = F.smooth_l1_loss(state_action_values, expected_state_action_values)

        # Optimize the model
        self.optimizer.zero_grad()
        loss.backward()

        # Gradient clipping to prevent exploding gradients
        torch.nn.utils.clip_grad_value_(self.policy_net.parameters(), 100)
        self.optimizer.step()
        return float(loss.item())

    def update_target_network(self):
        self.target_net.load_state_dict(self.policy_net.state_dict())

    def decay_epsilon(self):
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
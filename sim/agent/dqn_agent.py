import torch
import torch.optim as optim
import torch.nn.functional as F
import random
import numpy as np
from sim.agent.dqn_model import TradingDQN, ReplayBuffer


class DQNAgent:
    def __init__(self, state_dim: int, action_dim: int, lr: float = 1e-3, gamma: float = 0.99,
                 epsilon_start: float = 1.0, epsilon_min: float = 0.01, epsilon_decay: float = 0.995):
        assert state_dim > 0 and action_dim > 0, "Invalid dimensions"

        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay

        # Determine device implicitly based on hardware availability
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Initialize primary and target networks
        self.policy_net = TradingDQN(state_dim, action_dim).to(self.device)
        self.target_net = TradingDQN(state_dim, action_dim).to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()  # Target network does not learn directly

        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=lr)
        self.memory = ReplayBuffer(capacity=10000)

    def select_action(self, state: np.ndarray) -> int:
        assert state.ndim == 1, "State must be 1D"

        # Exploration
        if random.random() < self.epsilon:
            return random.randrange(self.action_dim)

        # Exploitation
        with torch.no_grad():
            state_tensor = torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(self.device)
            q_values = self.policy_net(state_tensor)
            return q_values.argmax().item()

    def train_step(self, batch_size: int):
        if len(self.memory) < batch_size:
            return  # Fail fast bypass: not enough data to train yet

        states, actions, rewards, next_states, dones = self.memory.sample(batch_size)

        states = states.to(self.device)
        actions = actions.to(self.device)
        rewards = rewards.to(self.device)
        next_states = next_states.to(self.device)
        dones = dones.to(self.device)

        # Current Q values
        q_values = self.policy_net(states)
        state_action_values = q_values.gather(1, actions.unsqueeze(1)).squeeze(1)

        # Next Q values from target network
        with torch.no_grad():
            next_q_values = self.target_net(next_states)
            max_next_q_values = next_q_values.max(1)[0]

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

    def update_target_network(self):
        self.target_net.load_state_dict(self.policy_net.state_dict())

    def decay_epsilon(self):
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
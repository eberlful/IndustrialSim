"""Compact action-conditioned JEPA and the preregistered experimental OPF variant."""
from __future__ import annotations
import torch
from torch import nn

from features import ACTION_DIM


class GraphWorldModel(nn.Module):
    def __init__(self, channels=14, width=128, machine_types=("none",), variant="jepa"):
        super().__init__()
        if width % 4 or variant not in ("jepa", "opf", "supervised"):
            raise ValueError("Four equal factors and a known model variant are required")
        self.channels, self.width, self.variant = channels, width, variant
        self.machine_types = tuple(sorted(set(machine_types) | {"generic"}))
        self.encoders = nn.ModuleList([nn.GRU(2 * channels, width, batch_first=True)
                                      for _ in self.machine_types])
        self.static = nn.Linear(7, width)
        self.messages = nn.ModuleList([nn.Linear(2 * width, width) for _ in range(2)])
        self.projector = nn.Linear(width, width)
        self.transition = nn.GRUCell(ACTION_DIM + 2, width)
        self.readout = nn.Sequential(nn.Linear(width, width), nn.GELU(), nn.Linear(width, channels))
        self.quality_readout = nn.Linear(width, 1)
        generator = torch.Generator().manual_seed(20260923)
        directions = torch.randn(width, 32, generator=generator)
        self.register_buffer("sigreg_directions", directions / directions.norm(dim=0))

    def encode(self, x, graph, static, machine_types, local=False):
        # x: batch, time, nodes, channels*2. Shared temporal weights by type.
        b, t, n, _ = x.shape
        z = x.new_zeros((b, n, self.width))
        for key in sorted(set(machine_types)):
            ids = [i for i, label in enumerate(machine_types) if label == key]
            module_index = self.machine_types.index(key) if key in self.machine_types else self.machine_types.index("generic")
            node_history = x[:, :, ids].permute(0, 2, 1, 3).reshape(b * len(ids), t, -1)
            _, hidden = self.encoders[module_index](node_history)
            z[:, ids] = hidden[-1].reshape(b, len(ids), self.width)
        z = z + self.static(static).unsqueeze(0)
        if not local:
            z = self.communicate(z, graph)
        return self.projector(z)

    def communicate(self, z, graph):
        for layer in self.messages:
            incoming = torch.matmul(graph, z)
            z = z + torch.tanh(layer(torch.cat((z, incoming), dim=-1)))
        return z

    def predict(self, z, actions, plan, graph, local=False):
        b, n, d = z.shape
        inputs = torch.cat((actions, plan[:, None, :].expand(-1, n, -1)), dim=-1)
        updated = self.transition(inputs.reshape(b * n, -1), z.reshape(b * n, d)).reshape(b, n, d)
        return updated if local else self.communicate(updated, graph)

    def rollout(self, x, actions, plan, graph, static, machine_types, local=False):
        z = self.encode(x, graph, static, machine_types, local)
        latents = []
        for step in range(actions.shape[1]):
            z = self.predict(z, actions[:, step], plan[:, step], graph, local)
            latents.append(z)
        latent = torch.stack(latents, dim=1)
        return self.readout(latent), latent

    def sigreg(self, representations):
        """Sketched Gaussian characteristic-function matching, quadrature on [0,3]."""
        samples = representations.reshape(-1, self.width) @ self.sigreg_directions
        points = torch.linspace(0, 3, 9, device=samples.device)
        phase = samples[..., None] * points
        real = phase.cos().mean(dim=0)
        imag = phase.sin().mean(dim=0)
        target = torch.exp(-0.5 * points.square())
        integrand = ((real - target).square() + imag.square()) * target
        return torch.trapezoid(integrand, points, dim=-1).mean()

    def orthogonality(self, representations):
        samples = representations.reshape(-1, 4, self.width // 4)
        samples = samples - samples.mean(dim=0, keepdim=True)
        result = samples.new_zeros(())
        for left in range(4):
            for right in range(left + 1, 4):
                covariance = samples[:, left].T @ samples[:, right] / max(1, len(samples) - 1)
                result = result + covariance.square().mean()
        return result / 6

    def loss(self, x, future_contexts, actions, plan, graph, static, machine_types, mask, local=False):
        prediction, latent = self.rollout(x, actions, plan, graph, static, machine_types, local)
        if self.variant == "supervised":
            target = future_contexts[:, :, -1, :, :self.channels]
            return ((prediction - target).square() * mask).sum() / mask.sum().clamp_min(1)
        targets = torch.stack([self.encode(future_contexts[:, step], graph, static, machine_types, local)
                               for step in range(actions.shape[1])], dim=1)
        valid_nodes = mask.any(dim=-1).unsqueeze(-1)
        prediction_loss = ((latent - targets.detach()).square() * valid_nodes).sum() / (
            valid_nodes.sum().clamp_min(1) * self.width)
        loss = prediction_loss + 0.09 * (self.sigreg(targets) + self.sigreg(latent)) / 2
        if self.variant == "opf":
            loss = loss + 0.01 * self.orthogonality(targets)
        return loss

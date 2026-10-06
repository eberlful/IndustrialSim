"""Run with uv run pytest tests/ml; no simulator state imports."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pytest

torch = pytest.importorskip("torch")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml"))
from features import encode_actions, fit_normalization, balanced_mae
from model import GraphWorldModel
from pipeline import grouped_bootstrap, load_model


def test_jepa_and_opf_share_capacity_but_opf_penalizes_correlated_factors():
    torch.manual_seed(11)
    jepa = GraphWorldModel(width=32)
    torch.manual_seed(11)
    opf = GraphWorldModel(width=32, variant="opf")
    assert sum(p.numel() for p in jepa.parameters()) == sum(p.numel() for p in opf.parameters())
    independent = torch.randn(2000, 32)
    correlated = independent[:, :8].repeat(1, 4)
    assert opf.orthogonality(correlated) > opf.orthogonality(independent) * 10
    assert jepa.sigreg(torch.zeros(2000, 32)) > jepa.sigreg(independent)


def test_action_times_statuses_and_graph_bindings_are_preserved():
    graph = {"node_ids": ["m", "st"], "routes": {"r": (0, 1)}}
    timed = {"time_ns": 15_000_000_000, "status": "applied",
             "action": {"action_type": "machine_mode", "target_id": "m", "mode": "boost"}}
    encoded = encode_actions(graph, [timed], 0, 2)
    assert encoded[0, 0, 8] == .5 and encoded[0, 0, 11] == 1
    assert not encoded[1].any()
    timed["status"] = "no_effect"
    assert not encode_actions(graph, [timed], 0, 2).any()


def test_normalization_rejects_test_data_and_mae_weights_groups_equally():
    with pytest.raises(ValueError, match="training episodes"):
        fit_normalization([{"split": "test"}], 14)
    actual = np.zeros((2, 3, 14))
    predicted = np.zeros_like(actual)
    predicted[..., :5] = 2
    predicted[..., 5:] = 4
    assert balanced_mae(predicted, actual, np.ones_like(actual, dtype=bool)) == 3


def test_bootstrap_uses_paired_root_groups():
    result = grouped_bootstrap({"root1": 1., "root2": 2.}, {"root1": 2., "root2": 3.})
    assert result["ci95"] == [-1., -1.] and result["opf_superior"]
    with pytest.raises(ValueError, match="identical"):
        grouped_bootstrap({"root1": 1.}, {"root2": 2.})


def test_trainable_action_effect_and_round_trip_on_changed_graph_size(tmp_path):
    torch.set_num_threads(2)
    torch.manual_seed(22)
    model = GraphWorldModel(width=32, variant="supervised")
    optimizer = torch.optim.Adam(model.parameters(), lr=.01)
    x = torch.zeros(8, 32, 2, 28)
    graph = torch.eye(2)
    static = torch.zeros(2, 7)
    actions = torch.zeros(8, 3, 2, 24)
    actions[:, :, 0, 3] = 1
    modes = torch.tensor([-1., 1.] * 4)
    actions[:, :, 0, 11] = modes[:, None]
    plan = torch.zeros(8, 3, 2)
    future = torch.zeros(8, 3, 32, 2, 28)
    future[:, :, -1, 0, 2] = modes[:, None] * torch.arange(1, 4)[None, :]
    mask = torch.ones(8, 3, 2, 14)
    for _ in range(100):
        optimizer.zero_grad()
        loss = model.loss(x, future, actions, plan, graph, static, ["none"] * 2, mask)
        loss.backward()
        optimizer.step()
    prediction, _ = model.rollout(x, actions, plan, graph, static, ["none"] * 2)
    assert prediction[1, -1, 0, 2] - prediction[0, -1, 0, 2] > 4
    path = tmp_path / "model.pt"
    torch.save({"schema_version": "industrial-world-model/1.0", "channels": 14, "width": 32,
                "machine_types": ["none"], "variant": "supervised", "state_dict": model.state_dict()}, path)
    loaded, _ = load_model(path)
    again, _ = loaded.rollout(x, actions, plan, graph, static, ["none"] * 2)
    assert torch.equal(prediction, again)
    changed, _ = loaded.rollout(torch.zeros(1,32,3,28), torch.zeros(1,3,3,24),
                                torch.zeros(1,3,2), torch.eye(3), torch.zeros(3,7), ["unknown"]*3)
    assert changed.shape == (1,3,3,14) and torch.isfinite(changed).all()


def test_future_contexts_are_shared_views_with_correct_temporal_alignment():
    from pipeline import windows
    graph = {"node_ids": ["m"], "node_types": ["machine"], "edges": [],
             "capacities": [1], "machine_types": ["generic"], "routes": {}}
    observations = [{"time_ns": step * 30_000_000_000, "values": [[float(step)] * 14],
                     "mask": [[True] * 14]} for step in range(50)]
    samples = windows([{"observations": observations, "graph": graph, "production_plan": [],
                        "actions": []}], {"mean": [0.] * 14, "std": [1.] * 14})
    first = samples[0]
    assert first["x"][-1, 0, 0] == 31
    assert first["future"][0, -1, 0, 0] == 32
    assert first["future"][-1, -1, 0, 0] == 41
    assert np.shares_memory(first["x"], first["future"])

"""JSON/NumPy feature boundary shared by ML training and inference.

This module only consumes portable artifacts, without importing simulator state.
"""
from __future__ import annotations
import hashlib
import json
import numpy as np

ACTION_TYPES = ("buffer_reorder", "routing", "dispatch", "machine_mode", "maintenance",
                "reconfiguration", "worker_reassignment", "quality_control")
ACTION_DIM = 24
STEP_NS = 30_000_000_000
ROLES = ("source", "sink", "station", "buffer", "machine", "worker")


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def adjacency(graph):
    n = len(graph["node_ids"])
    matrix = np.eye(n, dtype=np.float32)
    for source, target in graph["edges"]:
        matrix[target, source] += 1
    return matrix / matrix.sum(axis=1, keepdims=True)


def static_features(graph):
    result = np.zeros((len(graph["node_ids"]), len(ROLES) + 1), dtype=np.float32)
    for i, role in enumerate(graph["node_types"]):
        result[i, ROLES.index(role)] = 1
        result[i, -1] = np.log1p(graph["capacities"][i])
    return result


def encode_actions(graph, actions, start_ns, horizon):
    result = np.zeros((horizon, len(graph["node_ids"]), ACTION_DIM), dtype=np.float32)
    index = {nid: i for i, nid in enumerate(graph["node_ids"])}
    for timed in actions:
        if timed.get("status", "applied") != "applied":
            continue
        dt = timed["time_ns"] - start_ns
        if dt < 0 or dt >= horizon * STEP_NS:
            continue
        step = dt // STEP_NS
        a = timed["action"]
        kind = a["action_type"]
        row = np.zeros(ACTION_DIM, dtype=np.float32)
        row[ACTION_TYPES.index(kind)] = 1
        row[8] = (dt % STEP_NS) / STEP_NS
        row[9] = a.get("duration_ns", 0) / STEP_NS
        row[10] = a.get("cost", 0)
        row[11] = {"eco": -1., "nominal": 0., "boost": 1.}.get(a.get("mode"), 0.)
        row[12] = float(a.get("trigger_maintenance", False))
        row[13:16] = [a.get(key) or 0 for key in
                      ("inspection_intensity", "sampling_rate", "release_threshold")]
        row[16] = a.get("configuration", {}).get("cycle_time_multiplier", 1.) - 1
        row[17] = float(a.get("assigned_station_id") is not None)
        row[18] = len(a.get("qualifications") or [])
        order = a.get("new_order", [])
        # Unit IDs are never embedded: permutation relative to a public previous
        # order is supplied by the bridge/dataset instead.
        row[19] = float(a.get("reorder_distance", 0.))
        row[20] = len(order)
        row[21] = float(a.get("vehicle_id") is not None)
        row[22] = float(a.get("head_due_delta_hours", 0.))
        binding = index.get(a.get("target_id"))
        route = graph.get("routes", {}).get(a.get("route_id"))
        if route:
            binding = route[0]
            result[step, route[1], :8] += row[:8]
            result[step, route[1], 22] += 1
        if binding is not None:
            result[step, binding] += row
        assigned = index.get(a.get("assigned_station_id"))
        if assigned is not None:
            result[step, assigned, 23] += 1
    return result


def plan_features(production_plan, start_ns, horizon):
    result = np.zeros((horizon, 2), dtype=np.float32)
    for entry in production_plan:
        time = entry["release_time_ns"]
        if start_ns <= time < start_ns + horizon * STEP_NS:
            step = (time - start_ns) // STEP_NS
            result[step, 0] += entry.get("quantity", 1)
            due = entry.get("due_date_ns")
            result[step, 1] += 0 if due is None else max(0, (due - time) / (3600 * 10**9))
    return result


def fit_normalization(episodes, channels):
    total = np.zeros(channels, dtype=np.float64)
    square = np.zeros(channels, dtype=np.float64)
    count = np.zeros(channels, dtype=np.float64)
    for episode in episodes:
        if episode["split"] != "train":
            raise ValueError("Normalization may only fit training episodes")
        values = np.asarray([o["values"] for o in episode["observations"]], dtype=np.float64)
        mask = np.asarray([o["mask"] for o in episode["observations"]], dtype=bool)
        total += (values * mask).sum(axis=(0, 1))
        square += (values ** 2 * mask).sum(axis=(0, 1))
        count += mask.sum(axis=(0, 1))
    mean = total / np.maximum(count, 1)
    std = np.sqrt(np.maximum(0, square / np.maximum(count, 1) - mean ** 2))
    std[std < 1e-6] = 1.
    for index in (11, 12):
        if index < channels and std[index] == 1.:
            std[index] = 1e9  # One second for an unvarying nanosecond channel.
    return {"mean": mean.tolist(), "std": std.tolist(), "counts": count.tolist()}


def normalized_context(observations, normalization):
    values = np.asarray([o["values"] for o in observations], dtype=np.float32)
    mask = np.asarray([o["mask"] for o in observations], dtype=np.float32)
    normalized = (values - np.asarray(normalization["mean"], dtype=np.float32)) / np.asarray(normalization["std"], dtype=np.float32)
    return np.concatenate((normalized * mask, mask), axis=-1)


def balanced_mae(prediction, actual, mask):
    errors = np.abs(prediction - actual)
    means = []
    for lo, hi in ((0, 5), (5, errors.shape[-1])):
        per_channel = []
        for channel in range(lo, hi):
            valid = mask[..., channel].astype(bool)
            if valid.any():
                per_channel.append(float(errors[..., channel][valid].mean()))
        if not per_channel:
            raise ValueError("Primary metric requires observations from both channel groups")
        means.append(float(np.mean(per_channel)))
    return float(np.mean(means))

"""Artifact-only training/evaluation. Run in the shared Python 3.12 environment, without simulator state imports."""
from __future__ import annotations

from collections import defaultdict
import copy
import json
from pathlib import Path
import platform
import time

import numpy as np
import torch

from features import (adjacency, balanced_mae, digest, encode_actions, fit_normalization,
                      normalized_context, plan_features, static_features)
from model import GraphWorldModel

SCHEMA = "industrial-world-model/1.0"


def load_dataset(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["status"] != "complete" or manifest["schema_version"] != SCHEMA:
        raise ValueError("Incomplete or incompatible dataset")
    episodes = []
    roots, seeds = {}, {}
    for item in manifest["episodes"]:
        for mapping, key in ((roots, item["root_id"]), (seeds, item["seed"])):
            if key in mapping and mapping[key] != item["split"]:
                raise ValueError("Dataset split leakage")
            mapping[key] = item["split"]
        episode = json.loads((directory / item["path"]).read_text())
        if digest(episode) != item["hash"]:
            raise ValueError("Dataset integrity failure")
        obs = episode["observations"]
        if any(o["episode_id"] != episode["episode_id"] or o["branch_id"] != episode["branch_id"] for o in obs):
            raise ValueError("Episode/branch boundary crossed")
        if any(b["time_ns"] - a["time_ns"] != 30_000_000_000 for a, b in zip(obs, obs[1:])):
            raise ValueError("Broken sample grid")
        # Integrity is checked on the full portable artifact. Keep only inputs
        # consumed by training in RAM; individual reading/findings records remain
        # available on disk and are already represented by masked channels.
        episode["observations"] = [{key: o[key] for key in
            ("episode_id", "branch_id", "time_ns", "values", "mask")} for o in obs]
        episode["actions"] = [a for a in episode["actions"] if a["status"] == "applied"]
        episodes.append(episode)
    if not any(e["split"] == "train" for e in episodes) or not any(e["split"] == "validation" for e in episodes):
        raise ValueError("Training and validation splits required")
    return manifest, episodes


def windows(episodes, normalization, context=32, horizon=10, stride=4):
    result = []
    for episode in episodes:
        observations = episode["observations"]
        normalized = normalized_context(observations, normalization)
        masks = np.asarray([o["mask"] for o in observations], dtype=np.float32)
        # Overlapping contexts are views of one episode array. Materializing all
        # ten future contexts per window would multiply study host RAM by 320.
        contexts = np.moveaxis(np.lib.stride_tricks.sliding_window_view(
            normalized, context, axis=0), -1, 1)
        for stop in range(context, len(observations) - horizon + 1, stride):
            start_ns = observations[stop - 1]["time_ns"]
            future = contexts[stop - context + 1:stop - context + horizon + 1]
            result.append({"episode": episode, "start_ns": start_ns,
                "stop": stop,
                "x": normalized[stop-context:stop], "future": future,
                "mask": masks[stop:stop+horizon],
                "actions": encode_actions(episode["graph"], episode["actions"], start_ns, horizon),
                "plan": plan_features(episode["production_plan"], start_ns, horizon)})
    if not result:
        raise ValueError("Dataset contains no complete study windows")
    return result


def batches(samples, batch_size, seed):
    groups = defaultdict(list)
    for sample in samples:
        groups[digest(sample["episode"]["graph"])].append(sample)
    rng = np.random.default_rng(seed)
    result = []
    for key in sorted(groups):
        group = groups[key]
        indices = rng.permutation(len(group))
        result.extend([[group[i] for i in indices[start:start+batch_size]]
                       for start in range(0, len(group), batch_size)])
    rng.shuffle(result)
    return result


def tensors(batch, device):
    graph = batch[0]["episode"]["graph"]
    tensor = lambda data: torch.as_tensor(np.asarray(data), dtype=torch.float32, device=device)
    return (tensor([s["x"] for s in batch]), tensor([s["future"] for s in batch]),
            tensor([s["actions"] for s in batch]), tensor([s["plan"] for s in batch]),
            tensor(adjacency(graph)), tensor(static_features(graph)), graph["machine_types"],
            tensor([s["mask"] for s in batch]))


def infer(model, sample, device):
    model.eval()
    x, future, actions, plan, graph, static, types, mask = tensors([sample], device)
    with torch.no_grad():
        prediction, latent = model.rollout(x, actions, plan, graph, static, types)
        quality = model.quality_readout(latent).sigmoid()
    return prediction[0].cpu().numpy(), quality[0, :, :, 0].cpu().numpy()


def validate(model, samples, device):
    scores = defaultdict(list)
    for sample in samples:
        prediction, _ = infer(model, sample, device)
        truth = sample["future"][:, -1, :, :model.channels]
        scores[sample["episode"]["root_id"]].append(balanced_mae(prediction, truth, sample["mask"]))
    return float(np.mean([np.mean(v) for v in scores.values()]))


def train_variant(episodes, normalization, variant, seed, output, settings, deadline=None):
    torch.manual_seed(seed)
    np.random.seed(seed)
    device = settings["device"]
    torch.set_num_threads(settings.get("cpu_threads", 2))
    train_episodes = [e for e in episodes if e["split"] == "train"]
    val_episodes = [e for e in episodes if e["split"] == "validation"]
    machine_types = sorted({t for e in train_episodes for t in e["graph"]["machine_types"]})
    model = GraphWorldModel(len(normalization["mean"]), settings["width"], machine_types, variant).to(device)
    training = windows(train_episodes, normalization)
    validation = windows(val_episodes, normalization)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    best, best_state, log = float("inf"), None, []
    rounds = settings.get("local_epochs", 2) + settings.get("global_epochs", 10)
    readout_parameters = list(model.readout.parameters()) + list(model.quality_readout.parameters())
    readout_optimizer = torch.optim.AdamW(readout_parameters, lr=1e-3)
    start = time.monotonic()
    for epoch in range(rounds):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Study budget exhausted; incomplete model must not be evaluated")
        local = epoch < settings.get("local_epochs", 2)
        model.train()
        for parameter in model.parameters():
            parameter.requires_grad_(True)
        losses = []
        for batch in batches(training, settings["batch_size"], seed + epoch):
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Study GPU time budget exhausted")
            args = tensors(batch, device)
            optimizer.zero_grad(set_to_none=True)
            loss = model.loss(*args, local=local)
            if not torch.isfinite(loss):
                raise ValueError("Non-finite training loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.)
            optimizer.step()
            losses.append(float(loss.detach()))
        if local:
            log.append({"epoch": epoch, "stage": "local", "loss": float(np.mean(losses))})
            continue
        # Train observable and quality readouts on frozen dynamics. Quality targets
        # are increments of observed inspection findings, never latent defects.
        for parameter in model.parameters():
            parameter.requires_grad_(False)
        for parameter in readout_parameters:
            parameter.requires_grad_(True)
        for _ in range(settings.get("readout_epochs", 1)):
            for batch in batches(training, settings["batch_size"], seed + epoch):
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("Training budget exhausted during frozen readout fitting")
                x, future, actions, plan, graph, static, types, mask = tensors(batch, device)
                with torch.no_grad():
                    _, latent = model.rollout(x, actions, plan, graph, static, types)
                output_values = model.readout(latent)
                actual = future[:, :, -1, :, :model.channels]
                loss = ((output_values - actual).square() * mask).sum() / mask.sum().clamp_min(1)
                # Only stations with a declared findings channel have labels.
                quality_mask = mask[:, :, :, 7]
                mean = normalization["mean"][7]
                std = normalization["std"][7]
                latest = x[:, -1, :, 7] * std + mean
                count = actual[:, :, :, 7] * std + mean
                quality_target = (count > latest[:, None, :]).float()
                quality_loss = torch.nn.functional.binary_cross_entropy_with_logits(
                    model.quality_readout(latent).squeeze(-1), quality_target, reduction="none")
                loss = loss + (quality_loss * quality_mask).sum() / quality_mask.sum().clamp_min(1)
                readout_optimizer.zero_grad(set_to_none=True)
                loss.backward()
                readout_optimizer.step()
        val = validate(model, validation, device)
        log.append({"epoch": epoch, "stage": "global", "loss": float(np.mean(losses)), "validation_mae_10": val})
        if val < best:
            best, best_state = val, {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
    if best_state is None:
        raise ValueError("At least one global training epoch required")
    model.load_state_dict(best_state)
    artifact = {"schema_version": SCHEMA, "variant": variant, "seed": seed,
                "width": settings["width"], "channels": model.channels,
                "machine_types": machine_types, "normalization": normalization,
                "state_dict": best_state, "validation_mae_10": best,
                "parameter_count": sum(p.numel() for p in model.parameters()),
                "training_log": log, "runtime": {"python": platform.python_version(),
                "torch": str(torch.__version__), "device": device, "hip": torch.version.hip},
                "elapsed_seconds": time.monotonic() - start}
    torch.save(artifact, output)
    return artifact


def load_model(path, device="cpu"):
    artifact = torch.load(path, map_location=device, weights_only=True)
    if artifact["schema_version"] != SCHEMA:
        raise ValueError("Incompatible model artifact")
    model = GraphWorldModel(artifact["channels"], artifact["width"],
                            artifact["machine_types"], artifact["variant"]).to(device)
    model.load_state_dict(artifact["state_dict"])
    model.eval()
    return model, artifact


def grouped_bootstrap(left, right, seed=20260923, repetitions=10000):
    if set(left) != set(right) or not left:
        raise ValueError("Paired comparison requires identical nonempty root groups")
    difference = np.asarray([left[key] - right[key] for key in sorted(left)])
    rng = np.random.default_rng(seed)
    draws = difference[rng.integers(0, len(difference), (repetitions, len(difference)))].mean(axis=1)
    low, high = np.quantile(draws, [.025, .975])
    return {"difference_opf_minus_jepa": float(difference.mean()), "ci95": [float(low), float(high)],
            "episode_differences": {key: float(left[key] - right[key]) for key in sorted(left)},
            "opf_superior": bool(high < 0), "root_groups": len(left), "bootstrap_repetitions": repetitions}


def evaluate_model(model, artifact, episodes, device="cpu", label_directory=None):
    records = []
    for split in sorted({e["split"] for e in episodes} - {"train", "validation"}):
        scores = defaultdict(list)
        quality_labels, quality_probs = [], []
        latent_labels, latent_probs = [], []
        labels_by_episode = {}
        for sample in windows([e for e in episodes if e["split"] == split], artifact["normalization"]):
            prediction, probabilities = infer(model, sample, device)
            actual = sample["future"][:, -1, :, :model.channels]
            score = balanced_mae(prediction, actual, sample["mask"])
            scores[sample["episode"]["root_id"]].append(score)
            observed = sample["mask"][:, :, 7].astype(bool)
            mean, std = artifact["normalization"]["mean"][7], artifact["normalization"]["std"][7]
            last = sample["x"][-1, :, 7] * std + mean
            labels = actual[:, :, 7] * std + mean > last[None, :]
            quality_labels.extend(labels[observed].tolist())
            quality_probs.extend(probabilities[observed].tolist())
            if label_directory is not None:
                episode_id = sample["episode"]["episode_id"]
                if episode_id not in labels_by_episode:
                    labels_by_episode[episode_id] = json.loads((Path(label_directory) / (episode_id + ".labels.json")).read_text())
                labels = labels_by_episode[episode_id]
                graph = sample["episode"]["graph"]
                for step in range(len(probabilities)):
                    label = labels[sample["stop"] + step]
                    for node, kind in enumerate(graph["node_types"]):
                        if kind != "station":
                            continue
                        units = [uid for uid, location in label["unit_locations"].items() if location == graph["node_ids"][node]]
                        if units:
                            latent_labels.append(any(label["quality_state"][uid] != "nominal" for uid in units))
                            latent_probs.append(float(probabilities[step, node]))
        values = {key: float(np.mean(v)) for key, v in scores.items()}
        records.append({"split": split, "mae_10": float(np.mean(list(values.values()))),
                        "root_scores": values, "quality_findings_brier": float(np.mean(
                            (np.asarray(quality_probs) - np.asarray(quality_labels)) ** 2))
                            if quality_labels else None,
                        "quality_proxy_brier_on_hidden_defects": float(np.mean(
                            (np.asarray(latent_probs) - np.asarray(latent_labels)) ** 2)) if latent_labels else None})
    return records

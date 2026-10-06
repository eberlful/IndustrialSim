"""Closed-loop, counterfactual and long-duration evaluation of frozen models."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import time
from typing import Any

import numpy as np

from industrialsim.application import _compute_reward
from industrialsim.config import SimulationConfig
from industrialsim.world_model.contracts import CHANNELS, STEP_NS, StudyObservation, TimedAction, digest
from industrialsim.world_model.inference import ArtifactWorldModel
from industrialsim.world_model.observation import StudyObservationAdapter, graph_from_engine
from industrialsim.world_model.planning import CandidateCatalog
from industrialsim.world_model.provider import WorldModelDecisionProvider
from industrialsim.world_model.study import (StudyEngine, StudySettings, ExplorationProvider,
    install_sampling, research_configuration, verify_manifest)


def evaluate_control(dataset: Path, models: Path, output: Path,
                     device: str = "cpu", deadline: float | None = None,
                     smoke: bool = False) -> dict[str, Any]:
    manifest = verify_manifest(dataset)
    training = json.loads((models / "training.json").read_text())
    if training["status"] != "complete" or training["dataset_hash"] != manifest["dataset_hash"]:
        raise ValueError("Control benchmark requires matching frozen model artifacts")
    if training["smoke"] and not smoke:
        raise ValueError("Smoke-trained weights cannot be reported as full study models")
    output.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {"status": "incomplete", "smoke": smoke, "episodes": [],
                             "counterfactual": [], "causes": [], "stability": [], "action_effect_counts": {}}
    def save() -> None:
        (output / "control.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    def check_budget() -> None:
        if deadline is not None and time.monotonic() >= deadline:
            save()
            raise TimeoutError("GPU budget exhausted during control benchmark")
    settings = StudySettings(**manifest["settings"])
    adapter = StudyObservationAdapter(settings.noise_scale, settings.missing_probability)
    worker = Path(__file__).resolve().parents[3] / "ml/worker.py"
    selected = []
    for split in ("test", "unknown_parameters", "unknown_topology", "unknown_combinations"):
        roots = [item for item in manifest["episodes"] if item["split"] == split and
                 item["root_id"] == item["episode_id"]]
        selected.extend(sorted(roots, key=lambda item: item["seed"])[:1 if smoke else 3])
    model_items = training["models"][:1] if smoke else training["models"]
    effect_counts: Counter[str] = Counter()
    save()
    for item in selected:
        config = SimulationConfig.model_validate_json((dataset / (item["episode_id"] + ".config.json")).read_text())
        heuristic = StudyEngine.create(config)
        assert isinstance(heuristic, StudyEngine)
        heuristic.decision_provider = ExplorationProvider(heuristic, item["split"], "heuristic")
        install_sampling(heuristic, adapter, item["episode_id"] + "-heuristic", settings)
        heuristic.run(pause_at_ns=30 * 10**9 if smoke else None)
        observation = adapter.observe(heuristic, graph_from_engine(heuristic), "evaluation")
        metrics = {name: observation.values[0][CHANNELS.index(name)] for name in CHANNELS[8:]}
        reward, _ = _compute_reward(metrics, config.reward_policy)
        report["episodes"].append({"root_id": item["root_id"], "split": item["split"],
            "provider": "heuristic", "metrics": metrics, "reward": reward,
            "fallbacks": len(heuristic.decision_diagnostics)})
        for model_item in model_items:
            check_budget()
            path = models / model_item["path"]
            import hashlib
            if hashlib.sha256(path.read_bytes()).hexdigest() != model_item["weight_hash"]:
                raise ValueError("Control model weight hash mismatch")
            with ArtifactWorldModel(path, worker, device) as model:
                engine = StudyEngine.create(config)
                assert isinstance(engine, StudyEngine)
                assert config.reward_policy is not None
                provider = WorldModelDecisionProvider(model,
                    CandidateCatalog(sorted(engine.stations), ({"cycle_time_multiplier": .85},
                                                              {"cycle_time_multiplier": 1.15})),
                    config.reward_policy, [p.model_dump(mode="json") for p in config.production_plan],
                    model_item["weight_hash"], beam_width=1 if smoke else 32)
                engine.decision_provider = provider
                install_sampling(engine, adapter, item["episode_id"] + "-" + model_item["path"], settings)
                # Budget check at every consistent Decision Batch, not only between episodes.
                original_decide = provider.decide
                def bounded_decide(batch: Any) -> Any:
                    if deadline is not None and time.monotonic() >= deadline:
                        engine.is_aborted = True
                        engine.abort_reason = "Study GPU budget exhausted"
                    check_budget()
                    return original_decide(batch)
                provider.decide = bounded_decide  # type: ignore[method-assign]
                engine.run(pause_at_ns=30 * 10**9 if smoke else None)
                check_budget()
                observation = adapter.observe(engine, graph_from_engine(engine), "evaluation")
                metrics = {name: observation.values[0][CHANNELS.index(name)] for name in CHANNELS[8:]}
                reward, _ = _compute_reward(metrics, config.reward_policy)
                for action in engine.action_evidence:
                    if action.status == "applied":
                        effect_counts[action.action["action_type"]] += 1
                report["episodes"].append({"root_id": item["root_id"], "split": item["split"],
                    "provider": model_item["variant"], "seed": model_item["seed"],
                    "weight_hash": model_item["weight_hash"], "metrics": metrics, "reward": reward,
                    "fallbacks": provider.fallback_count, "candidate_inferences": provider.inference_count})
                save()
    # Direct alternative-action ranking: compare siblings under common randomness
    # and the identical recorded follow-up policy, never simulator lookahead in planning.
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in manifest["episodes"]:
        if item["split"] not in ("train", "validation") and item["episode_id"] != item["root_id"]:
            groups.setdefault(item["root_id"], []).append(item)
    for model_item in model_items:
        check_budget()
        with ArtifactWorldModel(models / model_item["path"], worker, device) as model:
            for root, siblings in sorted(groups.items()):
                if len(siblings) != 2:
                    continue
                predicted, actual = [], []
                for item in siblings:
                    data = json.loads((dataset / item["path"]).read_text())
                    history = [StudyObservation.from_dict(o) for o in data["observations"][:32]]
                    graph = graph_from_engine(StudyEngine.create(SimulationConfig.model_validate_json(
                        (dataset / (item["episode_id"] + ".config.json")).read_text())))
                    start = history[-1].time_ns
                    actions = [TimedAction(**a) for a in data["actions"] if start <= a["time_ns"] < start + 10 * STEP_NS]
                    result = model.rollout(history, graph, actions, data["production_plan"], 10)
                    config = SimulationConfig.model_validate_json((dataset / (item["episode_id"] + ".config.json")).read_text())
                    pred_reward, _ = _compute_reward(result.metrics[-1], config.reward_policy)
                    truth = data["observations"][41]["values"][0]
                    raw = {name: truth[CHANNELS.index(name)] for name in CHANNELS[8:]}
                    actual_reward, _ = _compute_reward(raw, config.reward_policy)
                    if pred_reward is None or actual_reward is None:
                        raise ValueError("Counterfactual evaluation requires a Reward Policy")
                    predicted.append(float(pred_reward))
                    actual.append(float(actual_reward))
                report["counterfactual"].append({"root_id": root, "model": model_item["path"],
                    "predicted_rewards": predicted, "actual_rewards": actual,
                    "ranking_correct": bool(np.sign(predicted[0]-predicted[1]) == np.sign(actual[0]-actual[1]))})
    if not smoke:
        # Hidden fault interventions are evaluation-only: the model receives the
        # sensor history and ordinary actions, never the injected cause itself.
        fault_config = research_configuration(settings, settings.seed + 2_000_000, "test")
        fault_parent = StudyEngine.create(fault_config)
        assert isinstance(fault_parent, StudyEngine)
        fault_parent.decision_provider = ExplorationProvider(fault_parent, "test", "heuristic")
        install_sampling(fault_parent, adapter, "fault-parent", settings)
        fault_parent.run(pause_at_ns=31 * STEP_NS)
        checkpoint = fault_parent.create_checkpoint()
        graph = graph_from_engine(fault_parent)
        normalization = json.loads((models / "normalization.json").read_text())
        scale = np.asarray(normalization["std"][:5])
        for cause in sorted(fault_parent.machines)[:3]:
            check_budget()
            fault = StudyEngine.restore(checkpoint, fault_config)
            assert isinstance(fault, StudyEngine)
            fault.machines[cause].health = max(0.0, fault.machines[cause].health - .4)
            fault.decision_provider = ExplorationProvider(fault, "test", "heuristic")
            install_sampling(fault, adapter, "fault-" + cause, settings)
            fault.run(pause_at_ns=checkpoint.simulated_time_ns + 10 * STEP_NS)
            history = fault_parent.study_observations[-32:]
            future = fault.study_observations[:10]
            truth = np.asarray([o.values for o in future])
            mask = np.asarray([o.mask for o in future])
            actions = [a for a in fault.action_evidence if a.status == "applied"]
            for model_item in model_items:
                with ArtifactWorldModel(models / model_item["path"], worker, device) as model:
                    result = model.rollout(history, graph, actions,
                        [p.model_dump(mode="json") for p in fault_config.production_plan], len(future))
                residual = np.abs(np.asarray(result.values)[..., :5] - truth[..., :5]) / scale
                residual *= mask[..., :5]
                ordered = []
                for node, node_id in enumerate(graph.node_ids):
                    deviations = residual[:, node].max(axis=-1)
                    crosses = np.flatnonzero(deviations > 3.)
                    first = int(crosses[0]) if len(crosses) else len(future)
                    ordered.append((first, -float(deviations.max()), node_id))
                ranking = [item[2] for item in sorted(ordered)]
                report["causes"].append({"model": model_item["path"], "injected_cause": cause,
                    "ranking": ranking, "cause_rank": ranking.index(cause) + 1,
                    "rule": "first normalized prediction deviation above 3, then residual magnitude"})
                save()
    if not smoke:
        check_budget()
        long_config = research_configuration(settings, settings.seed + 1_000_000, "test", long_term=True)
        long_engine = StudyEngine.create(long_config)
        assert isinstance(long_engine, StudyEngine)
        long_engine.decision_provider = ExplorationProvider(long_engine, "test", "heuristic")
        install_sampling(long_engine, adapter, "five-day-stability", settings)
        long_engine.run()
        # Forecast fixed settings from a 32-frame context for up to 1,000 steps.
        # Repeat this at fixed daily anchors throughout the five-day episode.
        graph = graph_from_engine(long_engine)
        for model_item in model_items:
            with ArtifactWorldModel(models / model_item["path"], worker, device, 300) as model:
                for day in range(5):
                    check_budget()
                    stop = 32 + day * 2880
                    history = long_engine.study_observations[stop-32:stop]
                    available = min(1000, len(long_engine.study_observations)-stop)
                    result = model.rollout(history, graph, [], [p.model_dump(mode="json") for p in long_config.production_plan], available)
                    values = np.asarray(result.values)
                    truth = np.asarray([o.values for o in long_engine.study_observations[stop:stop+available]])
                    masks = np.asarray([o.mask for o in long_engine.study_observations[stop:stop+available]])
                    errors = np.abs(values-truth)
                    report["stability"].append({"model": model_item["path"], "day": day,
                        "horizon": available, "finite": bool(np.isfinite(values).all()),
                        "raw_mae": float(errors[masks].mean())})
                    save()
    report["action_effect_counts"] = dict(effect_counts)
    report["status"] = "smoke_complete" if smoke else "complete"
    save()
    return report

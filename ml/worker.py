"""Python-3.12 worker: GPU preflight, study training, evaluation, JSONL inference."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

import numpy as np
import torch

from features import (adjacency, digest, encode_actions, fit_normalization,
                      normalized_context, plan_features, static_features, balanced_mae)
from model import GraphWorldModel
from pipeline import (evaluate_model, grouped_bootstrap, infer, load_dataset, load_model,
                      tensors, train_variant, windows)


def preflight():
    result = {"python": platform.python_version(), "torch": torch.__version__,
              "hip": torch.version.hip, "kfd_visible": Path("/dev/kfd").exists(),
              "gpu_available": torch.cuda.is_available(), "status": "unavailable"}
    if sys.version_info[:2] != (3, 12):
        result["reason"] = "ML worker requires Python 3.12"
    elif not torch.cuda.is_available():
        result["reason"] = "PyTorch has no accessible GPU; check ROCm build and /dev/kfd access"
    else:
        try:
            properties = torch.cuda.get_device_properties(0)
            free, total = torch.cuda.mem_get_info()
            result.update(device=properties.name, free_bytes=free, total_bytes=total)
            # Validate actual backpropagation, not merely device enumeration.
            model = GraphWorldModel(width=32).to("cuda")
            optimizer = torch.optim.AdamW(model.parameters())
            x = torch.randn(2, 32, 3, 28, device="cuda")
            actions = torch.zeros(2, 10, 3, 24, device="cuda")
            plan = torch.zeros(2, 10, 2, device="cuda")
            graph = torch.eye(3, device="cuda")
            static = torch.zeros(3, 7, device="cuda")
            _, latent = model.rollout(x, actions, plan, graph, static, ["none"] * 3)
            loss = latent.square().mean() + model.sigreg(latent)
            loss.backward()
            optimizer.step()
            torch.cuda.synchronize()
            result.update(status="ready", training_step_loss=float(loss.detach()))
        except Exception as exc:
            result.update(status="failed", reason=str(exc))
    return result


def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False))


def train(directory, output, device, smoke=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest, episodes = load_dataset(directory)
    normalization = fit_normalization([e for e in episodes if e["split"] == "train"], len(manifest["channels"]))
    settings = {"width": 128, "batch_size": 16, "local_epochs": 2, "global_epochs": 10,
                "readout_epochs": 1, "device": device, "cpu_threads": 2}
    if smoke:
        settings.update(width=32, batch_size=4, local_epochs=1, global_epochs=1)
    report = {"status": "incomplete", "study": "EXP-0005", "smoke": smoke,
              "dataset_hash": manifest["dataset_hash"], "models": [], "settings": settings,
              "source_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted(Path(__file__).parent.glob("*.py"))},
              "dataset_provenance": manifest.get("provenance", {})}
    save_json(output / "training.json", report)
    if device == "cuda":
        check = preflight()
        save_json(output / "gpu-preflight.json", check)
        if check["status"] != "ready":
            raise RuntimeError(check["reason"])
        torch.cuda.set_per_process_memory_fraction(min(1.0, 16 * 1024**3 / check["total_bytes"]))
    elif not smoke:
        raise ValueError("Full study requires GPU; CPU is reserved for integration smoke runs")
    start = time.monotonic()
    deadline = start + 7 * 3600 if not smoke else None
    # Time one representative complete forward/backward rollout and synchronize.
    pilot_samples = windows([e for e in episodes if e["split"] == "train"], normalization)
    machine_types = sorted({t for e in episodes if e["split"] == "train" for t in e["graph"]["machine_types"]})
    for width, batch_size in ((settings["width"], settings["batch_size"]), (64, 8), (32, 4)):
        pilot = None
        args = None
        try:
            pilot = GraphWorldModel(len(manifest["channels"]), width, machine_types).to(device)
            batch = [pilot_samples[0]] * batch_size
            args = tensors(batch, device)
            begin = time.monotonic()
            pilot.loss(*args).backward()
            if device == "cuda":
                torch.cuda.synchronize()
            seconds = time.monotonic() - begin
        except torch.OutOfMemoryError:
            report.setdefault("pilot_reductions", []).append({"width": width, "batch_size": batch_size,
                                                             "reason": "out_of_memory"})
            continue
        finally:
            del pilot, args
            if device == "cuda":
                torch.cuda.empty_cache()
        # Factor four reserves target encoding/readouts/validation and a separate
        # hour for official TimesFM inference plus downstream evaluation.
        estimate = seconds * max(1, len(pilot_samples) / batch_size) * 12 * 9 * 4
        report["pilot"] = {"seconds_per_batch": seconds, "estimated_training_seconds": estimate}
        if smoke or estimate <= 7 * 3600:
            settings.update(width=width, batch_size=batch_size)
            break
    else:
        save_json(output / "training.json", report)
        raise RuntimeError("Pilot predicts budget overflow even at width 32; study remains incomplete")
    save_json(output / "normalization.json", normalization)
    for variant in ("jepa", "opf", "supervised"):
        for seed in (11, 22, 33):
            path = output / f"{variant}-{seed}.pt"
            artifact = train_variant(episodes, normalization, variant, seed, path, settings, deadline)
            report["models"].append({"variant": variant, "seed": seed, "path": path.name,
                "weight_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
                "parameter_count": artifact["parameter_count"],
                "validation_mae_10": artifact["validation_mae_10"],
                "runtime": artifact["runtime"], "elapsed_seconds": artifact["elapsed_seconds"]})
            save_json(output / "training.json", report)
    report.update(status="complete", elapsed_seconds=time.monotonic()-start)
    save_json(output / "training.json", report)
    return report


def evaluate(directory, models, output, device, timesfm_checkpoint=None):
    manifest, episodes = load_dataset(directory)
    models = Path(models)
    training = json.loads((models / "training.json").read_text())
    if training["status"] != "complete" or training["dataset_hash"] != manifest["dataset_hash"]:
        raise ValueError("Model/dataset mismatch or incomplete training")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    results = {"status": "incomplete", "dataset_hash": manifest["dataset_hash"],
               "smoke": training["smoke"], "models": []}
    save_json(output / "evaluation.json", results)
    grouped = {}
    for item in training["models"]:
        path = models / item["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["weight_hash"]:
            raise ValueError("Model weight hash mismatch")
        model, artifact = load_model(path, device)
        records = evaluate_model(model, artifact, episodes, device, directory)
        results["models"].append({**item, "metrics": records})
        for record in records:
            if record["split"] == "unknown_combinations":
                grouped[item["variant"], item["seed"]] = record["root_scores"]
    if not grouped:
        raise ValueError("Missing primary held-out combination test")
    keys = set(grouped["jepa", 11])
    aggregate = {variant: {key: float(np.mean([grouped[variant, seed][key] for seed in (11,22,33)]))
                          for key in keys} for variant in ("jepa", "opf")}
    results["primary"] = grouped_bootstrap(aggregate["opf"], aggregate["jepa"])
    if training["smoke"]:
        results["primary"]["opf_superior"] = None
        results["primary"]["interpretation"] = "Integration test only; no study conclusion"
    normalization = json.loads((models / "normalization.json").read_text())
    persistence = []
    timesfm_records = []
    forecaster = None
    if timesfm_checkpoint:
        from huggingface_hub import HfApi, snapshot_download
        from timesfm3 import TimesFM3Evaluator, ModelConfig
        checkpoint_path = Path(timesfm_checkpoint)
        revision = None
        if not checkpoint_path.exists():
            revision = HfApi().model_info(timesfm_checkpoint).sha
            checkpoint_path = Path(snapshot_download(timesfm_checkpoint, revision=revision,
                cache_dir=str(output / "weights-cache")))
        checkpoint_hashes = {str(p.relative_to(checkpoint_path)): hashlib.file_digest(p.open("rb"), "sha256").hexdigest()
            for p in checkpoint_path.rglob("*") if p.is_file() and p.suffix in (".pt", ".pth", ".bin", ".safetensors")}
        if not checkpoint_hashes:
            raise ValueError("Official TimesFM checkpoint has no verifiable weight files")
        results["timesfm_checkpoint_provenance"] = {"revision": revision, "weight_hashes": checkpoint_hashes}
        forecaster = TimesFM3Evaluator(ModelConfig(checkpoint_path=str(checkpoint_path), device=device,
                                                  per_core_batch_size=1))
    for split in sorted({e["split"] for e in episodes} - {"train", "validation"}):
        from collections import defaultdict
        scores, tf_scores = defaultdict(list), defaultdict(list)
        for sample in windows([e for e in episodes if e["split"] == split], normalization):
            truth = sample["future"][:, -1, :, :len(manifest["channels"])]
            pred = np.repeat(sample["x"][-1:, :, :len(manifest["channels"])], 10, axis=0)
            root = sample["episode"]["root_id"]
            scores[root].append(balanced_mae(pred, truth, sample["mask"]))
            if forecaster is not None:
                # Strict forecast baseline: historical observations only, no future
                # actions, future telemetry, hidden state or surrogate weights.
                series = sample["x"][:, :, :len(manifest["channels"])]
                target = series.reshape(series.shape[0], -1).T
                masks = sample["x"][:, :, len(manifest["channels"]):].reshape(series.shape[0], -1).T
                known_plan = plan_features(sample["episode"]["production_plan"],
                    sample["start_ns"] - 31 * 30_000_000_000, 42).T
                outputs = list(forecaster.predict_batch([target], horizon=10, return_quantiles=False,
                    past_only_covariates=[masks], past_future_covariates=[known_plan], use_symmetric_averaging=False))
                point = np.asarray(outputs[0].forecast).T.reshape(10, series.shape[1], series.shape[2])
                tf_scores[root].append(balanced_mae(point, truth, sample["mask"]))
        persistence.append({"split": split, "mae_10": float(np.mean([np.mean(v) for v in scores.values()]))})
        if tf_scores:
            timesfm_records.append({"split": split, "mae_10": float(np.mean([np.mean(v) for v in tf_scores.values()]))})
    results["persistence"] = persistence
    results["timesfm"] = {"status": "complete" if forecaster else "pending",
                           "checkpoint": timesfm_checkpoint, "metrics": timesfm_records}
    results["status"] = "smoke_complete" if training["smoke"] else (
        "forecast_complete" if forecaster else "incomplete")
    save_json(output / "evaluation.json", results)
    primary = results["primary"]
    lines = ["# EXP-0005 forecast evaluation", "", f"Status: {results['status']}", "",
             f"Dataset SHA-256: `{manifest['dataset_hash']}`", "",
             "Primary endpoint: training-normalized ten-step MAE on unknown intervention combinations.",
             "Process signals and material flow each receive 50% weight; sibling branches share root groups.", "",
             f"OPF minus JEPA: {primary['difference_opf_minus_jepa']:.6g}; paired 95% CI: {primary['ci95']}.",
             f"Bootstrap: {primary['bootstrap_repetitions']} repetitions, {primary['root_groups']} root groups.", "",
             ("CPU integration only; no scientific superiority conclusion." if training["smoke"] else
              f"Preregistered OPF superiority criterion met: {primary['opf_superior']}."), "",
             f"Official TimesFM: {results['timesfm']['status']}.", "",
             "Per-episode differences, quality scores, model seeds and weight hashes are in `evaluation.json`.",
             "Closed-loop, cause ranking and five-day stability are separate control-stage artifacts."]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    return results


def serve(model_path, device):
    torch.set_num_threads(2)
    model, artifact = load_model(model_path, device)
    provenance = {"variant": artifact["variant"], "seed": artifact["seed"],
                  "weight_hash": hashlib.sha256(Path(model_path).read_bytes()).hexdigest()}
    for line in sys.stdin:
        try:
            request = json.loads(line)
            observations = request["history"][-32:]
            if not observations:
                raise ValueError("Empty observation history")
            observations = [observations[0]] * (32 - len(observations)) + observations
            graph = request["graph"]
            start = observations[-1]["time_ns"]
            horizon = request["horizon"]
            normalized = normalized_context(observations, artifact["normalization"])
            tensor = lambda value: torch.as_tensor(value, dtype=torch.float32, device=device)
            action_batches = request.get("action_batches", [request.get("actions", [])])
            all_values = []
            for begin in range(0, len(action_batches), 64):
                chunk = action_batches[begin:begin+64]
                with torch.no_grad():
                    prediction, _ = model.rollout(tensor(normalized)[None].expand(len(chunk), -1, -1, -1),
                        tensor(np.stack([encode_actions(graph, actions, start, horizon) for actions in chunk])),
                        tensor(plan_features(request["production_plan"], start, horizon))[None].expand(len(chunk), -1, -1),
                        tensor(adjacency(graph)), tensor(static_features(graph)), graph["machine_types"])
                values = prediction.cpu().numpy()
                values = values * np.asarray(artifact["normalization"]["std"]) + np.asarray(artifact["normalization"]["mean"])
                all_values.extend(values.tolist())
            response = {"status": "ok", "provenance": provenance}
            if "action_batches" in request:
                response["batches"] = all_values
            else:
                response["values"] = all_values[0]
        except Exception as exc:
            response = {"status": "error", "error": str(exc)}
        print(json.dumps(response, allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "train", "evaluate", "serve"))
    parser.add_argument("--dataset")
    parser.add_argument("--output")
    parser.add_argument("--models")
    parser.add_argument("--model")
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--timesfm-checkpoint")
    args = parser.parse_args()
    try:
        if args.device == "cuda" and args.command in ("evaluate", "serve"):
            total_bytes = torch.cuda.get_device_properties(0).total_memory
            torch.cuda.set_per_process_memory_fraction(min(1.0, 16 * 1024**3 / total_bytes))
        if args.command == "preflight":
            result = preflight()
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "ready" else 2
        if args.command == "serve":
            serve(args.model, args.device)
            return 0
        if args.command == "train":
            result = train(args.dataset, args.output, args.device, args.smoke)
        else:
            result = evaluate(args.dataset, args.models, args.output, args.device, args.timesfm_checkpoint)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

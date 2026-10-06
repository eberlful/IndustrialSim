"""Study subprocesses use the same project interpreter as the simulator."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from industrialsim.world_model.study import generate_dataset, load_settings, verify_manifest

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class StudyCommandResult:
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.data


def worker_command(command: str, *arguments: str,
                   timeout_seconds: float | None = None) -> dict[str, Any]:
    process = subprocess.run([sys.executable, str(ROOT / "ml/worker.py"), command, *arguments],
                             capture_output=True, text=True, timeout=timeout_seconds)
    try:
        data = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ML worker failed in the shared Python environment: {process.stderr[-2000:]}. "
                           "Install PyTorch in .venv as described in ml/README.md.") from exc
    if process.returncode and command != "preflight":
        raise RuntimeError(data.get("error", process.stderr[-2000:]))
    return data


def execute(args: Any) -> StudyCommandResult:
    output = Path(args.output_dir)
    if args.study_command == "generate":
        return StudyCommandResult(generate_dataset(output, load_settings(args.study_config)))
    if args.study_command == "preflight":
        check = worker_command("preflight", timeout_seconds=60)
        output.mkdir(parents=True, exist_ok=False)
        (output / "gpu-preflight.json").write_text(json.dumps(check, indent=2))
        return StudyCommandResult(check)
    if args.study_command == "train":
        verify_manifest(Path(args.dataset))
        options = ["--dataset", args.dataset, "--output", str(output), "--device", args.device]
        if args.smoke:
            options.append("--smoke")
        return StudyCommandResult(worker_command("train", *options))
    if args.study_command == "evaluate":
        options = ["--dataset", args.dataset, "--models", args.models, "--output", str(output), "--device", args.device]
        if args.timesfm_checkpoint:
            options += ["--timesfm-checkpoint", args.timesfm_checkpoint]
        return StudyCommandResult(worker_command("evaluate", *options))
    if args.study_command == "control":
        from industrialsim.world_model.control import evaluate_control
        return StudyCommandResult(evaluate_control(Path(args.dataset), Path(args.models), output,
                                                   args.device, smoke=args.smoke))
    # A full run is only declared complete after every study stage, including
    # actual TimesFM, closed-loop control and five-day stability, has completed.
    output.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {"study": "EXP-0005", "status": "incomplete", "stages": {}}
    report_path = output / "study.json"
    def save() -> None:
        report_path.write_text(json.dumps(report, indent=2, allow_nan=False))
    save()
    check = worker_command("preflight", timeout_seconds=60)
    report["stages"]["gpu_preflight"] = check
    save()
    if check["status"] != "ready":
        report["reason"] = check.get("reason", "GPU preflight failed")
        save()
        return StudyCommandResult(report)
    dataset = output / "dataset"
    report["stages"]["dataset"] = generate_dataset(dataset, load_settings(args.study_config))["dataset_hash"]
    save()
    start = time.monotonic()
    models, evaluation = output / "models", output / "evaluation"
    report["stages"]["training"] = worker_command("train", "--dataset", str(dataset),
        "--output", str(models), "--device", "cuda")
    save()
    remaining = 8 * 3600 - (time.monotonic() - start)
    if remaining <= 0:
        raise TimeoutError("GPU study budget exhausted before evaluation")
    report["stages"]["evaluation"] = worker_command("evaluate", "--dataset", str(dataset),
        "--models", str(models), "--output", str(evaluation), "--device", "cuda",
        "--timesfm-checkpoint", args.timesfm_checkpoint or "google/timesfm-3.0-pytorch",
        timeout_seconds=remaining)
    save()
    from industrialsim.world_model.control import evaluate_control
    remaining = 8 * 3600 - (time.monotonic() - start)
    report["stages"]["control"] = evaluate_control(dataset, models, output / "control",
        "cuda", deadline=time.monotonic() + max(0, remaining))
    if report["stages"]["control"]["status"] == "complete":
        report["status"] = "complete"
    save()
    return StudyCommandResult(report)

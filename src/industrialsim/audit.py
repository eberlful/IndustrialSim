from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
from typing import Any, Sequence
from io import StringIO
from ruamel.yaml import YAML
from pydantic import BaseModel, Field

from industrialsim.config import SimulationConfig
from industrialsim.checkpoint import compute_config_hash, compute_model_hash
from industrialsim.telemetry import TelemetryManager


class RunArtifactExistsError(FileExistsError):
    """Raised when attempting to overwrite an existing completed run artifact."""
    pass


class AuditRecord(BaseModel):
    record_id: int
    simulated_time_ns: int
    event_type: str
    episode_id: str
    branch_id: str | None = None
    batch_id: str | None = None
    entity_ids: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    def to_json_line(self) -> str:
        return json.dumps(self.model_dump(mode="json"), separators=(",", ":"))


class AuditLogger:
    def __init__(self, file_path: Path | None = None) -> None:
        self.file_path = file_path
        self._records: list[AuditRecord] = []
        self._next_record_id = 0
        self._file_handle = None
        if self.file_path is not None:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_handle = open(self.file_path, "a", encoding="utf-8")

    @property
    def records(self) -> list[AuditRecord]:
        return list(self._records)

    def record(
        self,
        event_type: str,
        simulated_time_ns: int,
        episode_id: str,
        branch_id: str | None = None,
        batch_id: str | None = None,
        entity_ids: Sequence[str] | None = None,
        provenance: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditRecord:
        record_id = self._next_record_id
        self._next_record_id += 1

        rec = AuditRecord(
            record_id=record_id,
            simulated_time_ns=simulated_time_ns,
            event_type=event_type,
            episode_id=episode_id,
            branch_id=branch_id,
            batch_id=batch_id,
            entity_ids=list(entity_ids or []),
            provenance=provenance,
            details=details or {},
        )
        self._records.append(rec)

        if self._file_handle is not None:
            self._file_handle.write(rec.to_json_line() + "\n")
            self._file_handle.flush()

        return rec

    def close(self) -> None:
        if self._file_handle is not None:
            self._file_handle.close()
            self._file_handle = None


def collect_runtime_metadata() -> dict[str, Any]:
    return {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "version_info": list(sys.version_info[:5]),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
    }


def collect_library_metadata() -> dict[str, str]:
    libs: dict[str, str] = {}
    for pkg in ("pydantic", "ruamel-yaml", "pytest", "pyarrow"):
        try:
            libs[pkg] = importlib.metadata.version(pkg)
        except Exception:
            pass
    return libs


def collect_calibration_metadata(config: SimulationConfig | None = None) -> dict[str, Any]:
    if config is not None and getattr(config, "calibration", None) is not None:
        cal = config.calibration
        return {
            "is_calibrated": cal.is_calibrated,
            "calibration_id": cal.calibration_id,
            "notes": cal.notes,
            "uncalibrated_parameters": list(cal.uncalibrated_parameters),
        }
    return {
        "is_calibrated": False,
        "calibration_id": None,
        "notes": "synthetic reference parameters; not calibrated for quantitative real-world prediction",
        "uncalibrated_parameters": [],
    }


class RunArtifactWriter:
    def __init__(
        self,
        output_dir: Path | str,
        config: SimulationConfig,
        episode_id: str,
        branch_id: str | None = None,
        parent_run_id: str | None = None,
        checkpoint_hash: str | None = None,
        plugin_metadata: dict[str, str] | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.config = config
        self.episode_id = episode_id
        self.branch_id = branch_id
        self.parent_run_id = parent_run_id
        self.checkpoint_hash = checkpoint_hash
        self.plugin_metadata = dict(plugin_metadata or {})
        self.manifest_path = self.output_dir / "manifest.json"
        self.incomplete_marker = self.output_dir / ".incomplete"
        self.audit_path = self.output_dir / "audit.jsonl"
        self.summary_path = self.output_dir / "summary.json"
        self.config_path = self.output_dir / "resolved_config.yaml"
        self.checkpoints_dir = self.output_dir / "checkpoints"

        self._check_for_existing_completed_run()
        self._initialize_run_dir()
        self.audit_logger = AuditLogger(self.audit_path)
        self.telemetry_manager = TelemetryManager(
            output_dir=self.output_dir,
            config=self.config.telemetry,
            episode_id=self.episode_id,
        )

    def _check_for_existing_completed_run(self) -> None:
        if self.manifest_path.exists():
            try:
                data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return
            if data.get("status") == "completed":
                raise RunArtifactExistsError(
                    f"Run directory '{self.output_dir}' already exists and is completed"
                )

    def _initialize_run_dir(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoints_dir.mkdir(exist_ok=True)

        # Write .incomplete marker
        self.incomplete_marker.write_text("in_progress\n", encoding="utf-8")

        # Compute canonical hashes
        model_hash = compute_model_hash(self.config)
        config_hash = compute_config_hash(self.config)

        # Write initial manifest marked as incomplete
        manifest_data: dict[str, Any] = {
            "schema_version": self.config.schema_version,
            "kernel_version": "1.0",
            "run_id": self.episode_id,
            "branch_id": self.branch_id,
            "parent_run_id": self.parent_run_id,
            "checkpoint_hash": self.checkpoint_hash,
            "status": "incomplete",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "runtime": collect_runtime_metadata(),
            "libraries": collect_library_metadata(),
            "model_hash": model_hash,
            "config_hash": config_hash,
            "plugin_metadata": self.plugin_metadata,
            "seed": self.config.seed,
            "calibration": collect_calibration_metadata(self.config),
        }
        self.manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        # Save resolved configuration in YAML format using ruamel.yaml
        yaml_writer = YAML(typ="safe", pure=True)
        buf = StringIO()
        yaml_writer.dump(self.config.model_dump(mode="json"), buf)
        self.config_path.write_text(buf.getvalue(), encoding="utf-8")

    def finalize(self, summary_dict: dict[str, Any], status: str = "completed") -> None:
        # Write summary
        self.summary_path.write_text(json.dumps(summary_dict, indent=2), encoding="utf-8")

        # Close audit logger and telemetry manager
        self.audit_logger.close()
        self.telemetry_manager.close()

        # Update manifest
        manifest_data: dict[str, Any] = {}
        if self.manifest_path.exists():
            manifest_data = json.loads(self.manifest_path.read_text(encoding="utf-8"))

        manifest_data["status"] = status
        manifest_data["completed_at"] = datetime.now(timezone.utc).isoformat()
        manifest_data["events_recorded"] = len(self.audit_logger.records)
        manifest_data["result_hash"] = summary_dict.get("result_hash")
        manifest_data["simulated_time_ns"] = summary_dict.get("simulated_time_ns")
        manifest_data["telemetry_fragments"] = (
            self.telemetry_manager.metrics_fragment_paths
            + self.telemetry_manager.training_fragment_paths
        )
        manifest_data["telemetry_record_count"] = (
            self.telemetry_manager.metrics_records_written
            + self.telemetry_manager.training_records_written
        )
        manifest_data["thinned_samples_count"] = self.telemetry_manager.thinned_samples_count
        manifest_data["plugin_metadata"] = self.plugin_metadata

        self.manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        # Remove incomplete marker on clean completion or deterministic termination
        if status in ("completed", "deadlocked") and self.incomplete_marker.exists():
            self.incomplete_marker.unlink()


def load_audit_log(path_or_run_dir: str | Path) -> list[AuditRecord]:
    p = Path(path_or_run_dir)
    if p.is_dir():
        p = p / "audit.jsonl"
    if not p.is_file():
        raise FileNotFoundError(f"Audit log not found at: {p}")

    records: list[AuditRecord] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                data = json.loads(line_str)
                records.append(AuditRecord.model_validate(data))
    return records


@dataclass(frozen=True)
class RunInspection:
    run_id: str
    status: str
    is_complete: bool
    created_at: str
    completed_at: str | None
    schema_version: str
    kernel_version: str
    simulated_time_ns: int
    config_hash: str
    model_hash: str
    root_seed: int
    audit_record_count: int
    has_audit_log: bool
    has_checkpoints: bool
    checkpoint_count: int
    has_summary: bool
    has_resolved_config: bool
    has_incomplete_marker: bool
    runtime_metadata: dict[str, Any] = field(default_factory=dict)
    library_metadata: dict[str, str] = field(default_factory=dict)
    calibration_metadata: dict[str, Any] = field(default_factory=dict)
    plugin_metadata: dict[str, str] = field(default_factory=dict)
    parent_run_id: str | None = None
    branch_id: str | None = None
    summary: dict[str, Any] | None = None
    branches: list[str] = field(default_factory=list)
    telemetry_fragments: list[str] = field(default_factory=list)
    telemetry_record_count: int = 0
    thinned_samples_count: int = 0
    raw_metrics: dict[str, Any] | None = None
    reward: float | None = None
    hard_constraints: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "is_complete": self.is_complete,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "schema_version": self.schema_version,
            "kernel_version": self.kernel_version,
            "simulated_time_ns": self.simulated_time_ns,
            "config_hash": self.config_hash,
            "model_hash": self.model_hash,
            "root_seed": self.root_seed,
            "audit_record_count": self.audit_record_count,
            "has_audit_log": self.has_audit_log,
            "has_checkpoints": self.has_checkpoints,
            "checkpoint_count": self.checkpoint_count,
            "has_summary": self.has_summary,
            "has_resolved_config": self.has_resolved_config,
            "has_incomplete_marker": self.has_incomplete_marker,
            "parent_run_id": self.parent_run_id,
            "branch_id": self.branch_id,
            "runtime_metadata": self.runtime_metadata,
            "library_metadata": self.library_metadata,
            "calibration_metadata": self.calibration_metadata,
            "plugin_metadata": self.plugin_metadata,
            "summary": self.summary,
            "branches": self.branches,
            "telemetry_fragments": self.telemetry_fragments,
            "telemetry_record_count": self.telemetry_record_count,
            "thinned_samples_count": self.thinned_samples_count,
            "raw_metrics": self.raw_metrics,
            "reward": self.reward,
            "hard_constraints": self.hard_constraints,
        }


def inspect_run(path: str | Path) -> RunInspection:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Run directory not found: {p}")

    run_dir = p.parent if p.is_file() and p.name == "manifest.json" else p
    if not run_dir.is_dir():
        raise ValueError(f"Run path is not a directory: {run_dir}")

    manifest_file = run_dir / "manifest.json"
    incomplete_marker = run_dir / ".incomplete"
    audit_file = run_dir / "audit.jsonl"
    summary_file = run_dir / "summary.json"
    config_file = run_dir / "resolved_config.yaml"
    checkpoints_dir = run_dir / "checkpoints"
    branches_dir = run_dir / "branches"

    if not manifest_file.exists() and not incomplete_marker.exists() and not audit_file.exists():
        raise ValueError(f"Directory '{run_dir}' is not a valid run artifact directory")

    manifest_data: dict[str, Any] = {}
    if manifest_file.exists():
        try:
            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception:
            manifest_data = {}

    summary_data: dict[str, Any] | None = None
    if not summary_file.exists() and (run_dir / "comparison_summary.json").exists():
        summary_file = run_dir / "comparison_summary.json"
    if summary_file.exists():
        try:
            summary_data = json.loads(summary_file.read_text(encoding="utf-8"))
        except Exception:
            summary_data = None

    has_incomplete = incomplete_marker.exists()
    status = manifest_data.get("status", "incomplete" if has_incomplete else "unknown")
    is_complete = (status == "completed") and not has_incomplete

    audit_count = 0
    has_audit = audit_file.is_file()
    if has_audit:
        try:
            with open(audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        audit_count += 1
        except OSError:
            pass

    checkpoint_count = 0
    if checkpoints_dir.is_dir():
        checkpoint_count = len(list(checkpoints_dir.glob("*.json")))
    has_checkpoints = checkpoint_count > 0

    branches: list[str] = []
    if branches_dir.is_dir():
        branches = sorted([d.name for d in branches_dir.iterdir() if d.is_dir()])

    simulated_time_ns = manifest_data.get("simulated_time_ns")
    if simulated_time_ns is None and summary_data is not None:
        simulated_time_ns = summary_data.get("simulated_time_ns", 0)
    if simulated_time_ns is None:
        simulated_time_ns = 0

    raw_metrics = summary_data.get("raw_metrics") if summary_data else None
    reward = summary_data.get("reward") if summary_data else None
    hard_constraints = summary_data.get("hard_constraints") if summary_data else None
    telemetry_fragments = list(manifest_data.get("telemetry_fragments", []))
    telemetry_record_count = int(manifest_data.get("telemetry_record_count", 0))
    thinned_samples_count = int(manifest_data.get("thinned_samples_count", 0))

    return RunInspection(
        run_id=manifest_data.get("run_id", run_dir.name),
        status=status,
        is_complete=is_complete,
        created_at=manifest_data.get("created_at", ""),
        completed_at=manifest_data.get("completed_at"),
        schema_version=manifest_data.get("schema_version", "unknown"),
        kernel_version=manifest_data.get("kernel_version", "unknown"),
        simulated_time_ns=int(simulated_time_ns),
        config_hash=manifest_data.get("config_hash", ""),
        model_hash=manifest_data.get("model_hash", ""),
        root_seed=manifest_data.get("seed", 0),
        audit_record_count=audit_count,
        has_audit_log=has_audit,
        has_checkpoints=has_checkpoints,
        checkpoint_count=checkpoint_count,
        has_summary=summary_file.is_file(),
        has_resolved_config=config_file.is_file(),
        has_incomplete_marker=has_incomplete,
        runtime_metadata=manifest_data.get("runtime", {}),
        library_metadata=manifest_data.get("libraries", {}),
        calibration_metadata=manifest_data.get("calibration", {}),
        plugin_metadata=manifest_data.get("plugin_metadata", {}),
        parent_run_id=manifest_data.get("parent_run_id"),
        branch_id=manifest_data.get("branch_id"),
        summary=summary_data,
        branches=branches,
        telemetry_fragments=telemetry_fragments,
        telemetry_record_count=telemetry_record_count,
        thinned_samples_count=thinned_samples_count,
        raw_metrics=raw_metrics,
        reward=reward,
        hard_constraints=hard_constraints,
    )


def inspect(source: Any) -> Any:
    if hasattr(source, "schema_version") and hasattr(source, "event_queue"):
        from industrialsim.checkpoint import inspect_checkpoint
        return inspect_checkpoint(source)

    if isinstance(source, dict) and "event_queue" in source:
        from industrialsim.checkpoint import inspect_checkpoint
        return inspect_checkpoint(source)

    p = Path(source)
    if not p.exists():
        raise FileNotFoundError(f"Path not found: {p}")

    if p.is_dir() or (p.is_file() and p.name == "manifest.json"):
        return inspect_run(p)

    try:
        from industrialsim.checkpoint import inspect_checkpoint
        return inspect_checkpoint(p)
    except Exception:
        if (p.parent / "manifest.json").exists():
            return inspect_run(p.parent)
        raise


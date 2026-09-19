from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from industrialsim.config import SimulationConfig


def compute_config_hash(cfg: Any) -> str:
    if hasattr(cfg, "model_dump"):
        raw = cfg.model_dump(mode="json")
    elif isinstance(cfg, dict):
        raw = cfg
    else:
        raise TypeError(f"Expected SimulationConfig or dict, got {type(cfg).__name__}")
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_model_hash(cfg: Any) -> str:
    if hasattr(cfg, "model_dump"):
        model_data = {
            "plant": cfg.plant.model_dump(mode="json") if cfg.plant else None,
            "material_flow": cfg.material_flow.model_dump(mode="json") if cfg.material_flow else None,
            "stations": [s.model_dump(mode="json") for s in cfg.stations],
        }
    elif isinstance(cfg, dict):
        model_data = {
            "plant": cfg.get("plant"),
            "material_flow": cfg.get("material_flow"),
            "stations": cfg.get("stations", []),
        }
    else:
        raise TypeError(f"Expected SimulationConfig or dict, got {type(cfg).__name__}")
    canonical = json.dumps(model_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IncompatibleCheckpointError(ValueError):
    """Raised when a checkpoint's compatibility metadata does not match the target runtime or model."""


class InvalidCheckpointError(ValueError):
    """Raised when a checkpoint file or data is corrupted, malformed, or fails integrity checks."""


@dataclass
class Checkpoint:
    schema_version: str
    kernel_version: str
    model_hash: str
    config_hash: str
    simulated_time_ns: int
    next_sequence: int
    events_processed: int
    event_queue: list[dict[str, Any]]
    domain_state: dict[str, Any]
    root_seed: int
    random_occurrence_counters: dict[str, int] = field(default_factory=dict)
    plugin_metadata: dict[str, str] = field(default_factory=dict)
    configuration: dict[str, Any] = field(default_factory=dict)
    checksum: str | None = None

    def __init__(
        self,
        schema_version: str,
        kernel_version: str,
        model_hash: str,
        config_hash: str,
        simulated_time_ns: int,
        events_processed: int,
        event_queue: list[dict[str, Any]],
        domain_state: dict[str, Any],
        root_seed: int,
        next_sequence: int | None = None,
        sequence_counter: int | None = None,
        random_occurrence_counters: dict[str, int] | None = None,
        plugin_metadata: dict[str, str] | None = None,
        configuration: dict[str, Any] | None = None,
        checksum: str | None = None,
    ) -> None:
        self.schema_version = schema_version
        self.kernel_version = kernel_version
        self.model_hash = model_hash
        self.config_hash = config_hash
        self.simulated_time_ns = simulated_time_ns
        if next_sequence is not None:
            self.next_sequence = next_sequence
        elif sequence_counter is not None:
            self.next_sequence = sequence_counter
        else:
            raise TypeError("Checkpoint requires either 'next_sequence' or 'sequence_counter'")
        self.events_processed = events_processed
        self.event_queue = event_queue
        self.domain_state = domain_state
        self.root_seed = root_seed
        self.random_occurrence_counters = random_occurrence_counters or {}
        self.plugin_metadata = plugin_metadata or {}
        self.configuration = configuration or {}
        self.checksum = checksum

    @property
    def sequence_counter(self) -> int:
        return self.next_sequence

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sequence_counter"] = self.next_sequence
        return data


@dataclass(frozen=True)
class CheckpointInspection:
    schema_version: str
    kernel_version: str
    model_hash: str
    config_hash: str
    simulated_time_ns: int
    next_sequence: int
    sequence_counter: int
    events_processed: int
    queue_size: int
    root_seed: int
    random_occurrence_counters: dict[str, int]
    plugin_metadata: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kernel_version": self.kernel_version,
            "model_hash": self.model_hash,
            "config_hash": self.config_hash,
            "simulated_time_ns": self.simulated_time_ns,
            "next_sequence": self.next_sequence,
            "sequence_counter": self.sequence_counter,
            "events_processed": self.events_processed,
            "queue_size": self.queue_size,
            "root_seed": self.root_seed,
            "random_occurrence_counters": self.random_occurrence_counters,
            "plugin_metadata": self.plugin_metadata,
        }


def _compute_checksum(data: dict[str, Any]) -> str:
    """Computes a SHA-256 integrity checksum over the canonical payload excluding 'checksum'."""
    payload_copy = {k: v for k, v in data.items() if k != "checksum"}
    canonical = json.dumps(payload_copy, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def serialize_checkpoint(checkpoint: Checkpoint) -> str:
    data = checkpoint.to_dict()
    data["checksum"] = _compute_checksum(data)
    return json.dumps(data, indent=2, sort_keys=True)


def deserialize_checkpoint(raw: str | dict[str, Any]) -> Checkpoint:
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception as e:
            raise InvalidCheckpointError(f"Checkpoint JSON decoding failed: {e}") from e
    elif isinstance(raw, dict):
        data = dict(raw)
    else:
        raise InvalidCheckpointError(f"Unsupported checkpoint input type: {type(raw).__name__}")

    if not isinstance(data, dict):
        raise InvalidCheckpointError("Checkpoint root structure must be a JSON object mapping")

    required_fields = [
        "schema_version",
        "kernel_version",
        "model_hash",
        "config_hash",
        "simulated_time_ns",
        "events_processed",
        "event_queue",
        "domain_state",
        "root_seed",
    ]
    missing = [f for f in required_fields if f not in data]
    if "next_sequence" not in data and "sequence_counter" not in data:
        missing.append("next_sequence")
    if missing:
        raise InvalidCheckpointError(f"Checkpoint data missing required fields: {missing}")

    raw_seq = data.get("next_sequence")
    if raw_seq is None:
        raw_seq = data.get("sequence_counter", 0)
    seq_val = int(raw_seq)

    # Checksum verification
    recorded_checksum = data.get("checksum")
    if recorded_checksum is not None:
        computed_checksum = _compute_checksum(data)
        if recorded_checksum != computed_checksum:
            raise InvalidCheckpointError(
                f"Checkpoint integrity check failed: payload checksum mismatch (expected {recorded_checksum}, got {computed_checksum})"
            )

    return Checkpoint(
        schema_version=str(data["schema_version"]),
        kernel_version=str(data["kernel_version"]),
        model_hash=str(data["model_hash"]),
        config_hash=str(data["config_hash"]),
        simulated_time_ns=int(data["simulated_time_ns"]),
        next_sequence=seq_val,
        events_processed=int(data["events_processed"]),
        event_queue=list(data["event_queue"]),
        domain_state=dict(data["domain_state"]),
        root_seed=int(data["root_seed"]),
        random_occurrence_counters=dict(data.get("random_occurrence_counters", {})),
        plugin_metadata=dict(data.get("plugin_metadata", {})),
        configuration=dict(data.get("configuration", {})),
        checksum=recorded_checksum,
    )



def save_checkpoint(checkpoint: Checkpoint, path: str | Path) -> None:
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    serialized = serialize_checkpoint(checkpoint)

    # Atomic write pattern: write to temporary file in the same directory, flush, sync, and replace.
    temp_file = tempfile.NamedTemporaryFile(
        dir=target_path.parent,
        prefix=f".{target_path.stem}_",
        suffix=".tmp",
        mode="w",
        encoding="utf-8",
        delete=False,
    )
    temp_path = Path(temp_file.name)
    try:
        temp_file.write(serialized)
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_file.close()
        os.replace(temp_path, target_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def load_checkpoint(path: str | Path) -> Checkpoint:
    file_path = Path(path)
    if not file_path.is_file():
        raise InvalidCheckpointError(f"Checkpoint file not found: {file_path}")

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        raise InvalidCheckpointError(f"Failed to read checkpoint file '{file_path}': {e}") from e

    return deserialize_checkpoint(content)


def inspect_checkpoint(source: str | Path | dict[str, Any] | Checkpoint) -> CheckpointInspection:
    if isinstance(source, Checkpoint):
        cp = source
    elif isinstance(source, (str, Path)) and Path(source).is_file():
        cp = load_checkpoint(source)
    else:
        cp = deserialize_checkpoint(source)  # type: ignore[arg-type]

    return CheckpointInspection(
        schema_version=cp.schema_version,
        kernel_version=cp.kernel_version,
        model_hash=cp.model_hash,
        config_hash=cp.config_hash,
        simulated_time_ns=cp.simulated_time_ns,
        next_sequence=cp.next_sequence,
        sequence_counter=cp.sequence_counter,
        events_processed=cp.events_processed,
        queue_size=len(cp.event_queue),
        root_seed=cp.root_seed,
        random_occurrence_counters=cp.random_occurrence_counters,
        plugin_metadata=cp.plugin_metadata,
    )

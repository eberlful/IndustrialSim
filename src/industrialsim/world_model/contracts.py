"""Portable study contracts. No ML runtime or simulator truth in model inputs."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, Sequence
import hashlib
import json
import math

SCHEMA_VERSION = "industrial-world-model/1.0"
STEP_NS = 30_000_000_000
CHANNELS = ("temperature", "vibration", "current", "pressure", "process_signal",
            "occupancy", "completed", "findings", "good_output", "scrap", "wip",
            "lateness_ns", "downtime_ns", "total_strategic_cost")
PROCESS_CHANNELS = tuple(range(5))
FLOW_CHANNELS = tuple(range(5, len(CHANNELS)))
ACTION_TYPES = ("buffer_reorder", "routing", "dispatch", "machine_mode", "maintenance",
                "reconfiguration", "worker_reassignment", "quality_control")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class SensorReading:
    time_ns: int
    entity_id: str
    channel: str
    unit: str
    value: float | None
    missing: bool = False
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.missing != (self.value is None):
            raise ValueError("Missing readings must contain null, never a fabricated value")
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("Sensor readings must be finite")


@dataclass(frozen=True)
class PlantGraph:
    node_ids: tuple[str, ...]
    node_types: tuple[str, ...]
    edges: tuple[tuple[int, int], ...]
    capacities: tuple[float, ...]
    # Explicit type labels, shared across configurations; no learned entity IDs.
    machine_types: tuple[str, ...]
    routes: dict[str, tuple[int, int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        size = len(self.node_ids)
        if len(set(self.node_ids)) != size or any(len(v) != size for v in
                (self.node_types, self.capacities, self.machine_types)):
            raise ValueError("Graph node metadata must be aligned and unique")
        if any(min(edge) < 0 or max(edge) >= size for edge in self.edges):
            raise ValueError("Graph edge outside node set")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlantGraph:
        return cls(tuple(data["node_ids"]), tuple(data["node_types"]),
                   tuple(tuple(e) for e in data["edges"]), tuple(data["capacities"]),
                   tuple(data["machine_types"]), {k: tuple(v) for k, v in data.get("routes", {}).items()})


@dataclass(frozen=True)
class StudyObservation:
    episode_id: str
    branch_id: str
    time_ns: int
    values: tuple[tuple[float, ...], ...]
    mask: tuple[tuple[bool, ...], ...]
    readings: tuple[SensorReading, ...] = ()
    findings: tuple[dict[str, Any], ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if len(self.values) != len(self.mask):
            raise ValueError("Observation values and masks must align")
        for row, mask in zip(self.values, self.mask):
            if len(row) != len(CHANNELS) or len(mask) != len(CHANNELS):
                raise ValueError("Observation channel mismatch")
            if not all(math.isfinite(v) for v in row):
                raise ValueError("Observation contains non-finite values")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StudyObservation:
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Incompatible study observation")
        return cls(data["episode_id"], data["branch_id"], data["time_ns"],
                   tuple(tuple(row) for row in data["values"]),
                   tuple(tuple(row) for row in data["mask"]),
                   tuple(SensorReading(**r) for r in data.get("readings", [])),
                   tuple(data.get("findings", [])))


@dataclass(frozen=True)
class TimedAction:
    time_ns: int
    action: dict[str, Any]
    status: str = "applied"
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.action.get("action_type") not in ACTION_TYPES:
            raise ValueError("Unknown action type")
        if self.status not in ("proposed", "applied", "rejected", "no_effect"):
            raise ValueError("Unknown action status")


@dataclass(frozen=True)
class RolloutResult:
    times_ns: tuple[int, ...]
    values: tuple[tuple[tuple[float, ...], ...], ...]
    metrics: tuple[dict[str, float], ...]
    provenance: dict[str, Any]


class IndustrialWorldModel(Protocol):
    def rollout(self, history: Sequence[StudyObservation], graph: PlantGraph,
                actions: Sequence[TimedAction], production_plan: Sequence[dict[str, Any]],
                horizon: int = 10) -> RolloutResult: ...


def portable(value: Any) -> dict[str, Any]:
    return asdict(value)

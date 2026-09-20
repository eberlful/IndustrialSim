from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, Callable, Literal, Sequence, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator

from industrialsim.config import (
    BufferThresholdTriggerConfig,
    RoutingDecisionTriggerConfig,
    DispatchDecisionTriggerConfig,
    MachineDecisionTriggerConfig,
    SafePointTriggerConfig,
)


class DecisionProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_id: str
    branch_id: str = "main"
    batch_id: str
    provider_id: str | None = None
    model_id: str | None = None
    prompt_id: str | None = None


class BufferOccupantSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str
    variant: str
    due_date_ns: int | None = None
    enter_time_ns: int | None = None
    findings_count: int = 0


class RouteSummaryObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    route_id: str
    source_node_id: str
    target_node_id: str
    transit_time_ns: int
    capacity: int | None = None
    current_occupancy: int = 0
    is_admissible: bool = True


class VehicleSummaryObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    vehicle_id: str
    location: str
    capabilities: list[str] = Field(default_factory=list)
    speed_multiplier: float = 1.0
    distance_to_pickup_ns: int = 0


class BufferObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    buffer_id: str
    capacity: int
    occupancy: int
    occupants: list[BufferOccupantSummary] = Field(default_factory=list)
    upstream_nodes: list[str] = Field(default_factory=list)
    downstream_nodes: list[str] = Field(default_factory=list)
    route_statuses: dict[str, Any] = Field(default_factory=dict)
    aggregate_metrics: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)


class RoutingObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    unit_id: str
    variant: str
    current_node_id: str
    due_date_ns: int | None = None
    findings_count: int = 0
    candidate_routes: list[RouteSummaryObservation] = Field(default_factory=list)
    aggregate_metrics: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)


class DispatchObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    order_id: str
    unit_id: str
    variant: str
    source_node_id: str
    target_node_id: str
    created_time_ns: int
    due_date_ns: int | None = None
    findings_count: int = 0
    candidate_routes: list[RouteSummaryObservation] = Field(default_factory=list)
    available_vehicles: list[VehicleSummaryObservation] = Field(default_factory=list)
    aggregate_metrics: dict[str, Any] = Field(default_factory=dict)


class MachineObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    machine_id: str
    health: float
    operating_mode: str = "nominal"
    available_modes: list[str] = Field(default_factory=list)
    is_in_maintenance: bool = False
    is_failed: bool = False
    physical_state: dict[str, float] = Field(default_factory=dict)
    maintenance_policy_summary: dict[str, Any] = Field(default_factory=dict)
    aggregate_metrics: dict[str, Any] = Field(default_factory=dict)


class QualityControlBounds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min_inspection_intensity: float = 0.0
    max_inspection_intensity: float = 1.0
    min_sampling_rate: float = 0.0
    max_sampling_rate: float = 1.0
    min_release_threshold: float = 0.0
    max_release_threshold: float = 1.0


class StrategicObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    target_id: str
    is_safe_point: bool = True
    allowed_actions: list[str] = Field(default_factory=list)
    current_configuration: dict[str, Any] = Field(default_factory=dict)
    quality_control_bounds: QualityControlBounds | None = None
    available_workers: list[str] = Field(default_factory=list)
    aggregate_metrics: dict[str, Any] = Field(default_factory=dict)


DecisionObservation = Union[
    BufferObservation,
    RoutingObservation,
    DispatchObservation,
    MachineObservation,
    StrategicObservation,
    dict[str, Any],
]


# Action Models
class BufferReorderAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_type: Literal["buffer_reorder"] = "buffer_reorder"
    schema_version: str = "1.0"
    target_id: str
    new_order: list[str]


class RoutingAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_type: Literal["routing"] = "routing"
    schema_version: str = "1.0"
    target_id: str
    route_id: str
    unit_id: str | None = None


class DispatchAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_type: Literal["dispatch"] = "dispatch"
    schema_version: str = "1.0"
    target_id: str
    route_id: str
    vehicle_id: str | None = None


class MachineModeAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_type: Literal["machine_mode"] = "machine_mode"
    schema_version: str = "1.0"
    target_id: str
    mode: str


class MaintenanceAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_type: Literal["maintenance"] = "maintenance"
    schema_version: str = "1.0"
    target_id: str
    trigger_maintenance: bool = True


class ReconfigurationAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_type: Literal["reconfiguration"] = "reconfiguration"
    schema_version: str = "1.0"
    target_id: str
    configuration: dict[str, Any]
    duration_ns: int = 0
    cost: float = 0.0


class WorkerReassignmentAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_type: Literal["worker_reassignment"] = "worker_reassignment"
    schema_version: str = "1.0"
    target_id: str
    assigned_station_id: str | None = None
    qualifications: list[str] | None = None
    duration_ns: int = 0
    cost: float = 0.0


class QualityControlAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_type: Literal["quality_control"] = "quality_control"
    schema_version: str = "1.0"
    target_id: str
    inspection_intensity: float | None = None
    sampling_rate: float | None = None
    release_threshold: float | None = None
    duration_ns: int = 0
    cost: float = 0.0


DecisionAction = Annotated[
    Union[
        BufferReorderAction,
        RoutingAction,
        DispatchAction,
        MachineModeAction,
        MaintenanceAction,
        ReconfigurationAction,
        WorkerReassignmentAction,
        QualityControlAction,
    ],
    Field(discriminator="action_type"),
]


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    request_id: str
    request_type: str = "buffer_threshold"
    time_ns: int
    target_id: str
    trigger_id: str | None = None
    is_safe_point: bool = False
    observation: Any
    action_schema: str = "buffer_reorder"

    @field_validator("observation", mode="before")
    @classmethod
    def _parse_observation(cls, v: Any) -> Any:
        if isinstance(v, dict):
            if "buffer_id" in v:
                return BufferObservation.model_validate(v)
            elif "order_id" in v and "available_vehicles" in v:
                return DispatchObservation.model_validate(v)
            elif "unit_id" in v and "candidate_routes" in v:
                return RoutingObservation.model_validate(v)
            elif "machine_id" in v:
                return MachineObservation.model_validate(v)
            elif "target_id" in v and ("allowed_actions" in v or "is_safe_point" in v or "quality_control_bounds" in v):
                return StrategicObservation.model_validate(v)
        return v


class DecisionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_id: str
    episode_id: str
    branch_id: str = "main"
    time_ns: int
    requests: list[DecisionRequest] = Field(default_factory=list)


class DecisionDiagnosticRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    target_id: str | None = None
    batch_id: str | None = None
    request_id: str | None = None


class DecisionBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    provenance: DecisionProvenance
    actions: Sequence[DecisionAction] = Field(default_factory=list)


def validate_decision_batch_response(
    batch: DecisionBatch,
    response: DecisionBatchResponse,
) -> tuple[bool, list[DecisionDiagnosticRecord]]:
    diagnostics: list[DecisionDiagnosticRecord] = []

    if response.batch_id != batch.batch_id:
        diagnostics.append(
            DecisionDiagnosticRecord(
                code="BATCH_ID_MISMATCH",
                message=f"Response batch_id '{response.batch_id}' does not match batch '{batch.batch_id}'",
                batch_id=batch.batch_id,
            )
        )

    # 1. Check for duplicate actions targeting the same entity (conflicts)
    targets_seen: set[str] = set()
    for action in response.actions:
        if action.target_id in targets_seen:
            diagnostics.append(
                DecisionDiagnosticRecord(
                    code="CONFLICTING_ACTIONS",
                    message=f"Multiple actions proposed for target '{action.target_id}' in batch '{batch.batch_id}'",
                    target_id=action.target_id,
                    batch_id=batch.batch_id,
                )
            )
        targets_seen.add(action.target_id)

    requested_target_ids = {req.target_id for req in batch.requests}
    for action in response.actions:
        if action.target_id not in requested_target_ids:
            diagnostics.append(
                DecisionDiagnosticRecord(
                    code="UNREQUESTED_TARGET",
                    message=f"Action proposed for target '{action.target_id}' which was not requested in batch '{batch.batch_id}'",
                    target_id=action.target_id,
                    batch_id=batch.batch_id,
                )
            )

    actions_by_target = {action.target_id: action for action in response.actions}

    # 2. Check for simultaneous competing resource claims across actions
    seen_vehicles: set[str] = set()
    seen_workers: set[str] = set()
    for action in response.actions:
        if isinstance(action, DispatchAction) and action.vehicle_id is not None:
            if action.vehicle_id in seen_vehicles:
                diagnostics.append(
                    DecisionDiagnosticRecord(
                        code="COMPETING_RESOURCE_CLAIMS",
                        message=f"Simultaneous dispatch actions claim the same vehicle '{action.vehicle_id}' in batch '{batch.batch_id}'",
                        target_id=action.target_id,
                        batch_id=batch.batch_id,
                    )
                )
            seen_vehicles.add(action.vehicle_id)
        elif isinstance(action, WorkerReassignmentAction):
            if action.target_id in seen_workers:
                diagnostics.append(
                    DecisionDiagnosticRecord(
                        code="COMPETING_RESOURCE_CLAIMS",
                        message=f"Simultaneous strategic actions claim the same worker '{action.target_id}' in batch '{batch.batch_id}'",
                        target_id=action.target_id,
                        batch_id=batch.batch_id,
                    )
                )
            seen_workers.add(action.target_id)

    # 3. Verify each request in the batch has a corresponding action and validate action specifics
    for req in batch.requests:
        target_action = actions_by_target.get(req.target_id)
        if target_action is None:
            diagnostics.append(
                DecisionDiagnosticRecord(
                    code="MISSING_ACTION",
                    message=f"No action proposed for request '{req.request_id}' targeting '{req.target_id}'",
                    target_id=req.target_id,
                    batch_id=batch.batch_id,
                    request_id=req.request_id,
                )
            )
            continue

        # Strategic Action Safety Check: only accepted at explicit safe decision points
        if isinstance(target_action, (ReconfigurationAction, WorkerReassignmentAction, QualityControlAction)):
            is_safe = req.is_safe_point
            if isinstance(req.observation, StrategicObservation) and not req.observation.is_safe_point:
                is_safe = False
            if not is_safe:
                diagnostics.append(
                    DecisionDiagnosticRecord(
                        code="UNSAFE_DECISION_POINT",
                        message=f"Strategic action '{target_action.action_type}' for '{target_action.target_id}' rejected: not at a safe decision point",
                        target_id=target_action.target_id,
                        batch_id=batch.batch_id,
                        request_id=req.request_id,
                    )
                )

        # Quality Control Bounds Check
        if isinstance(target_action, QualityControlAction):
            if isinstance(req.observation, StrategicObservation) and req.observation.quality_control_bounds is not None:
                bounds = req.observation.quality_control_bounds
                if (
                    target_action.inspection_intensity is not None
                    and not (bounds.min_inspection_intensity <= target_action.inspection_intensity <= bounds.max_inspection_intensity)
                ):
                    diagnostics.append(
                        DecisionDiagnosticRecord(
                            code="QUALITY_BOUNDS_EXCEEDED",
                            message=f"Quality inspection_intensity {target_action.inspection_intensity} is outside bounds [{bounds.min_inspection_intensity}, {bounds.max_inspection_intensity}]",
                            target_id=target_action.target_id,
                            batch_id=batch.batch_id,
                            request_id=req.request_id,
                        )
                    )
                if (
                    target_action.sampling_rate is not None
                    and not (bounds.min_sampling_rate <= target_action.sampling_rate <= bounds.max_sampling_rate)
                ):
                    diagnostics.append(
                        DecisionDiagnosticRecord(
                            code="QUALITY_BOUNDS_EXCEEDED",
                            message=f"Quality sampling_rate {target_action.sampling_rate} is outside bounds [{bounds.min_sampling_rate}, {bounds.max_sampling_rate}]",
                            target_id=target_action.target_id,
                            batch_id=batch.batch_id,
                            request_id=req.request_id,
                        )
                    )
                if (
                    target_action.release_threshold is not None
                    and not (bounds.min_release_threshold <= target_action.release_threshold <= bounds.max_release_threshold)
                ):
                    diagnostics.append(
                        DecisionDiagnosticRecord(
                            code="QUALITY_BOUNDS_EXCEEDED",
                            message=f"Quality release_threshold {target_action.release_threshold} is outside bounds [{bounds.min_release_threshold}, {bounds.max_release_threshold}]",
                            target_id=target_action.target_id,
                            batch_id=batch.batch_id,
                            request_id=req.request_id,
                        )
                    )

        # Validate BufferReorderAction against buffer observation
        if isinstance(target_action, BufferReorderAction) and isinstance(req.observation, BufferObservation):
            known_occupant_ids = [occ.unit_id for occ in req.observation.occupants]
            known_occupant_set = set(known_occupant_ids)

            # Check for unknown units
            for unit_id in target_action.new_order:
                if unit_id not in known_occupant_set:
                    diagnostics.append(
                        DecisionDiagnosticRecord(
                            code="UNKNOWN_UNIT",
                            message=f"Action references unknown unit '{unit_id}' for target '{req.target_id}'",
                            target_id=req.target_id,
                            batch_id=batch.batch_id,
                            request_id=req.request_id,
                        )
                    )

            # Check for duplicate units in new_order
            if len(target_action.new_order) != len(set(target_action.new_order)):
                diagnostics.append(
                    DecisionDiagnosticRecord(
                        code="DUPLICATE_UNIT",
                        message=f"Action contains duplicate unit IDs: {target_action.new_order}",
                        target_id=req.target_id,
                        batch_id=batch.batch_id,
                        request_id=req.request_id,
                    )
                )

            # Check occupant set completeness
            if set(target_action.new_order) != known_occupant_set:
                diagnostics.append(
                    DecisionDiagnosticRecord(
                        code="INVALID_OCCUPANT_SET",
                        message=f"Action new_order does not match set of current buffer occupants: expected {known_occupant_set}, got {set(target_action.new_order)}",
                        target_id=req.target_id,
                        batch_id=batch.batch_id,
                        request_id=req.request_id,
                    )
                )

    is_valid = len(diagnostics) == 0
    return is_valid, diagnostics


class DecisionProvider:
    """Protocol / base interface for in-process Decision Providers."""

    def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
        raise NotImplementedError


class FifoBufferFallbackPolicy:
    """Deterministic fallback policy preserving FIFO / arrival order, with earliest due date as tie-breaker."""

    def generate_fallback_actions(self, batch: DecisionBatch) -> list[BufferReorderAction]:
        actions: list[BufferReorderAction] = []
        for req in batch.requests:
            if isinstance(req.observation, BufferObservation):
                sorted_occupants = sorted(
                    req.observation.occupants,
                    key=lambda occ: (
                        occ.enter_time_ns if occ.enter_time_ns is not None else 0,
                        (0, occ.due_date_ns) if occ.due_date_ns is not None else (1, 0),
                        occ.unit_id,
                    ),
                )
                actions.append(
                    BufferReorderAction(
                        target_id=req.target_id,
                        new_order=[occ.unit_id for occ in sorted_occupants],
                    )
                )
        return actions


class BaselineDecisionProvider(DecisionProvider):
    """Deterministic baseline provider:
    - Queue priority: FIFO with earliest due date as tie-breaker.
    - Routing: Shortest admissible route.
    - Dispatch: Shortest admissible route and nearest suitable vehicle.
    - Machine: Health-based preventive maintenance (triggers maintenance if health <= threshold).
    """

    def __init__(
        self,
        provider_id: str = "baseline-provider",
        model_id: str = "deterministic-baseline",
    ) -> None:
        self.provider_id = provider_id
        self.model_id = model_id

    def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
        actions: list[DecisionAction] = []

        for req in batch.requests:
            obs = req.observation
            if isinstance(obs, BufferObservation) or req.action_schema == "buffer_reorder":
                occupants = obs.occupants if isinstance(obs, BufferObservation) else []
                sorted_occupants = sorted(
                    occupants,
                    key=lambda occ: (
                        occ.enter_time_ns if occ.enter_time_ns is not None else 0,
                        (0, occ.due_date_ns) if occ.due_date_ns is not None else (1, 0),
                        occ.unit_id,
                    ),
                )
                actions.append(
                    BufferReorderAction(
                        target_id=req.target_id,
                        new_order=[occ.unit_id for occ in sorted_occupants],
                    )
                )

            elif isinstance(obs, RoutingObservation) or req.action_schema == "routing":
                candidate_routes = obs.candidate_routes if isinstance(obs, RoutingObservation) else []
                admissible = [r for r in candidate_routes if r.is_admissible]
                if admissible:
                    sorted_routes = sorted(
                        admissible,
                        key=lambda r: (r.transit_time_ns, r.route_id),
                    )
                    best_route = sorted_routes[0]
                    unit_id = obs.unit_id if isinstance(obs, RoutingObservation) else req.target_id
                    actions.append(
                        RoutingAction(
                            target_id=req.target_id,
                            route_id=best_route.route_id,
                            unit_id=unit_id,
                        )
                    )

            elif isinstance(obs, DispatchObservation) or req.action_schema == "dispatch":
                candidate_routes = obs.candidate_routes if isinstance(obs, DispatchObservation) else []
                available_vehicles = obs.available_vehicles if isinstance(obs, DispatchObservation) else []
                admissible = [r for r in candidate_routes if r.is_admissible]
                if admissible:
                    if available_vehicles:
                        options = []
                        for r in admissible:
                            for v in available_vehicles:
                                effective_pickup_time = (
                                    int(round(v.distance_to_pickup_ns / v.speed_multiplier))
                                    if v.speed_multiplier > 0
                                    else v.distance_to_pickup_ns
                                )
                                options.append((r.transit_time_ns, effective_pickup_time, r.route_id, v.vehicle_id, r, v))
                        options.sort(key=lambda opt: (opt[0], opt[1], opt[2], opt[3]))
                        best = options[0]
                        actions.append(
                            DispatchAction(
                                target_id=req.target_id,
                                route_id=best[4].route_id,
                                vehicle_id=best[5].vehicle_id,
                            )
                        )
                    else:
                        sorted_routes = sorted(admissible, key=lambda r: (r.transit_time_ns, r.route_id))
                        best_route = sorted_routes[0]
                        actions.append(
                            DispatchAction(
                                target_id=req.target_id,
                                route_id=best_route.route_id,
                                vehicle_id=None,
                            )
                        )

            elif isinstance(obs, MachineObservation) or req.action_schema in ("machine_mode", "maintenance"):
                health = obs.health if isinstance(obs, MachineObservation) else 1.0
                policy = obs.maintenance_policy_summary if isinstance(obs, MachineObservation) else {}
                thresh = float(policy.get("health_threshold", 0.3)) if policy else 0.3
                is_maint = obs.is_in_maintenance if isinstance(obs, MachineObservation) else False
                is_failed = obs.is_failed if isinstance(obs, MachineObservation) else False
                if health <= thresh and not is_maint and not is_failed:
                    actions.append(
                        MaintenanceAction(
                            target_id=req.target_id,
                            trigger_maintenance=True,
                        )
                    )
                else:
                    actions.append(
                        MachineModeAction(
                            target_id=req.target_id,
                            mode="nominal",
                        )
                    )

        return DecisionBatchResponse(
            batch_id=batch.batch_id,
            provenance=DecisionProvenance(
                episode_id=batch.episode_id,
                branch_id=batch.branch_id,
                batch_id=batch.batch_id,
                provider_id=self.provider_id,
                model_id=self.model_id,
            ),
            actions=actions,
        )


class BaselineFallbackPolicy:
    """Deterministic fallback policy adhering to baseline rules."""

    def __init__(self) -> None:
        self._provider = BaselineDecisionProvider()

    def generate_fallback_actions(self, batch: DecisionBatch) -> list[DecisionAction]:
        resp = self._provider.decide(batch)
        return list(resp.actions)


@dataclass
class BufferTriggerRuntime:
    config: BufferThresholdTriggerConfig
    is_armed: bool = True
    last_dedup_key: str | None = None

    def check_transition(
        self,
        buffer_id: str,
        old_occupancy: int,
        new_occupancy: int,
        current_time_ns: int,
    ) -> bool:
        if buffer_id != self.config.buffer_id:
            return False

        # 1. Check re-arm condition if disarmed
        if not self.is_armed:
            assert self.config.rearm_threshold is not None
            if self.config.direction == "rising":
                if new_occupancy <= self.config.rearm_threshold:
                    self.is_armed = True
                    self.last_dedup_key = None
            else:
                if new_occupancy >= self.config.rearm_threshold:
                    self.is_armed = True
                    self.last_dedup_key = None

            if not self.is_armed:
                return False

        # 2. Check firing threshold if armed
        fires = False
        if self.config.direction == "rising":
            if old_occupancy < self.config.threshold <= new_occupancy:
                fires = True
        else:
            if old_occupancy > self.config.threshold >= new_occupancy:
                fires = True

        if not fires:
            return False

        # 3. Check deduplication key (cannot loop indefinitely on unchanged state or identical transition)
        dedup_key = f"{self.config.id}:{buffer_id}:{current_time_ns}:{old_occupancy}->{new_occupancy}"
        if self.last_dedup_key == dedup_key:
            return False

        # Arm state update
        self.last_dedup_key = dedup_key
        self.is_armed = False
        return True

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "id": self.config.id,
            "is_armed": self.is_armed,
            "last_dedup_key": self.last_dedup_key,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        self.is_armed = state.get("is_armed", True)
        self.last_dedup_key = state.get("last_dedup_key")


@dataclass
class MachineTriggerRuntime:
    config: MachineDecisionTriggerConfig
    is_armed: bool = True
    last_dedup_key: str | None = None

    def check_condition(
        self,
        machine_id: str,
        health: float,
        current_time_ns: int,
    ) -> bool:
        if machine_id != self.config.machine_id:
            return False

        # Re-arm condition
        if not self.is_armed:
            rearm = self.config.rearm_threshold if self.config.rearm_threshold is not None else 0.7
            if health >= rearm:
                self.is_armed = True
                self.last_dedup_key = None
            else:
                return False

        # Firing condition
        if health <= self.config.health_threshold:
            time_key = f"{self.config.id}:{machine_id}:{current_time_ns}"
            if self.last_dedup_key and self.last_dedup_key.startswith(time_key):
                return False
            dedup_key = f"{time_key}:{health:.4f}"
            self.last_dedup_key = dedup_key
            self.is_armed = False
            return True

        return False

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "id": self.config.id,
            "is_armed": self.is_armed,
            "last_dedup_key": self.last_dedup_key,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        self.is_armed = state.get("is_armed", True)
        self.last_dedup_key = state.get("last_dedup_key")


@dataclass
class SafePointTriggerRuntime:
    config: SafePointTriggerConfig
    last_dedup_key: str | None = None

    def check_time(self, current_time_ns: int) -> bool:
        fires = False
        if current_time_ns in self.config.times_ns:
            fires = True
        elif self.config.interval_ns is not None and self.config.interval_ns > 0:
            if current_time_ns > 0 and current_time_ns % self.config.interval_ns == 0:
                fires = True

        if not fires:
            return False

        dedup_key = f"{self.config.id}:{self.config.target_id}:{current_time_ns}"
        if self.last_dedup_key == dedup_key:
            return False

        self.last_dedup_key = dedup_key
        return True

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "id": self.config.id,
            "last_dedup_key": self.last_dedup_key,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        self.last_dedup_key = state.get("last_dedup_key")


@dataclass
class RoutingTriggerRuntime:
    config: RoutingDecisionTriggerConfig
    last_dedup_key: str | None = None

    def check_routing(self, node_id: str, unit_id: str, current_time_ns: int) -> bool:
        if node_id != self.config.node_id:
            return False
        dedup_key = f"{self.config.id}:{node_id}:{unit_id}:{current_time_ns}"
        if self.last_dedup_key == dedup_key:
            return False
        self.last_dedup_key = dedup_key
        return True

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "id": self.config.id,
            "last_dedup_key": self.last_dedup_key,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        self.last_dedup_key = state.get("last_dedup_key")


@dataclass
class DispatchTriggerRuntime:
    config: DispatchDecisionTriggerConfig
    last_dedup_key: str | None = None

    def check_dispatch(self, order_id: str, current_time_ns: int) -> bool:
        dedup_key = f"{self.config.id}:{order_id}:{current_time_ns}"
        if self.last_dedup_key == dedup_key:
            return False
        self.last_dedup_key = dedup_key
        return True

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "id": self.config.id,
            "last_dedup_key": self.last_dedup_key,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        self.last_dedup_key = state.get("last_dedup_key")


@dataclass
class DecisionBatchCoordinator:
    episode_id: str
    branch_id: str = "main"
    batch_counter: int = 0
    pending_requests: list[DecisionRequest] = field(default_factory=list)

    def add_request(self, request: DecisionRequest) -> None:
        self.pending_requests.append(request)

    def has_pending(self) -> bool:
        return len(self.pending_requests) > 0

    def form_batch(
        self,
        time_ns: int,
        observation_builder: Callable[[Any], Any] | None = None,
    ) -> DecisionBatch | None:
        if not self.pending_requests:
            return None
        self.batch_counter += 1
        batch_id = f"batch-{self.batch_counter:04d}"
        requests = []
        for req in self.pending_requests:
            if observation_builder is not None:
                try:
                    obs = observation_builder(req)
                except TypeError:
                    obs = observation_builder(req.target_id)
                req = req.model_copy(update={"observation": obs})
            requests.append(req)
        batch = DecisionBatch(
            batch_id=batch_id,
            episode_id=self.episode_id,
            branch_id=self.branch_id,
            time_ns=time_ns,
            requests=requests,
        )
        self.pending_requests.clear()
        return batch

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "branch_id": self.branch_id,
            "batch_counter": self.batch_counter,
            "pending_requests": [req.model_dump() for req in self.pending_requests],
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        self.episode_id = state.get("episode_id", self.episode_id)
        self.branch_id = state.get("branch_id", self.branch_id)
        self.batch_counter = state.get("batch_counter", 0)
        self.pending_requests = [
            DecisionRequest.model_validate(item) for item in state.get("pending_requests", [])
        ]





from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from pydantic import BaseModel, ConfigDict, Field

from industrialsim.config import BufferThresholdTriggerConfig


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


class BufferReorderAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_type: str = "buffer_reorder"
    target_id: str
    new_order: list[str]


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    request_id: str
    request_type: str = "buffer_threshold"
    time_ns: int
    target_id: str
    trigger_id: str | None = None
    observation: BufferObservation
    action_schema: str = "buffer_reorder"


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
    actions: list[BufferReorderAction] = Field(default_factory=list)


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

    # Check for duplicate actions targeting the same node/buffer (conflicts)
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

    # Verify each request in the batch has a corresponding action
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

        # Validate action against buffer observation
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
    """Deterministic fallback policy preserving FIFO / arrival order."""

    def generate_fallback_actions(self, batch: DecisionBatch) -> list[BufferReorderAction]:
        actions: list[BufferReorderAction] = []
        for req in batch.requests:
            sorted_occupants = sorted(
                req.observation.occupants,
                key=lambda occ: (
                    occ.enter_time_ns if occ.enter_time_ns is not None else 0,
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
        observation_builder: Callable[[str], BufferObservation] | None = None,
    ) -> DecisionBatch | None:
        if not self.pending_requests:
            return None
        self.batch_counter += 1
        batch_id = f"batch-{self.batch_counter:04d}"
        requests = []
        for req in self.pending_requests:
            if observation_builder is not None:
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





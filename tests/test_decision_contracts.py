import pytest
from industrialsim.decisions import (
    DecisionProvenance,
    BufferOccupantSummary,
    BufferObservation,
    BufferReorderAction,
    DecisionRequest,
    DecisionBatch,
    DecisionBatchResponse,
    DecisionDiagnosticRecord,
    validate_decision_batch_response,
    FifoBufferFallbackPolicy,
)


def test_decision_provenance_and_request_contract_serialization() -> None:
    provenance = DecisionProvenance(
        episode_id="ep-1",
        branch_id="main",
        batch_id="batch-001",
        provider_id="provider-gpt",
        model_id="gpt-4o",
        prompt_id="prompt-v1",
    )
    assert provenance.episode_id == "ep-1"
    assert provenance.provider_id == "provider-gpt"

    occupant = BufferOccupantSummary(
        unit_id="unit-1",
        variant="sedan",
        due_date_ns=10_000_000,
        enter_time_ns=5_000_000,
        findings_count=1,
    )
    # Ensure no latent quality attributes exist on occupant summary
    assert not hasattr(occupant, "quality_state")
    assert not hasattr(occupant, "defects")

    obs = BufferObservation(
        schema_version="1.0",
        buffer_id="buf-1",
        capacity=5,
        occupancy=1,
        occupants=[occupant],
        upstream_nodes=["st-1"],
        downstream_nodes=["st-2"],
        route_statuses={"r-1": {"capacity": 2, "occupancy": 0}},
        aggregate_metrics={"completed_units": 10, "wip": 3, "simulation_time_ns": 5_000_000},
        history=[{"time_ns": 5_000_000, "event": "entered", "unit_id": "unit-1"}],
    )

    req = DecisionRequest(
        request_id="req-001",
        request_type="buffer_threshold",
        time_ns=5_000_000,
        target_id="buf-1",
        observation=obs,
        action_schema="buffer_reorder",
    )

    batch = DecisionBatch(
        batch_id="batch-001",
        episode_id="ep-1",
        time_ns=5_000_000,
        requests=[req],
    )

    data = batch.model_dump()
    assert data["batch_id"] == "batch-001"
    assert len(data["requests"]) == 1
    assert data["requests"][0]["observation"]["buffer_id"] == "buf-1"

    restored = DecisionBatch.model_validate(data)
    assert restored.batch_id == batch.batch_id
    assert restored.requests[0].observation.occupants[0].unit_id == "unit-1"


def test_validate_decision_batch_response_success() -> None:
    obs = BufferObservation(
        schema_version="1.0",
        buffer_id="buf-1",
        capacity=5,
        occupancy=2,
        occupants=[
            BufferOccupantSummary(unit_id="unit-1", variant="sedan"),
            BufferOccupantSummary(unit_id="unit-2", variant="suv"),
        ],
    )
    req = DecisionRequest(
        request_id="req-001",
        request_type="buffer_threshold",
        time_ns=1000,
        target_id="buf-1",
        observation=obs,
    )
    batch = DecisionBatch(
        batch_id="b-1",
        episode_id="ep-1",
        time_ns=1000,
        requests=[req],
    )

    response = DecisionBatchResponse(
        batch_id="b-1",
        provenance=DecisionProvenance(episode_id="ep-1", batch_id="b-1", provider_id="test-provider"),
        actions=[BufferReorderAction(target_id="buf-1", new_order=["unit-2", "unit-1"])],
    )

    is_valid, diagnostics = validate_decision_batch_response(batch, response)
    assert is_valid is True
    assert len(diagnostics) == 0


def test_validate_decision_batch_response_diagnostics_on_invalid_and_conflicts() -> None:
    obs1 = BufferObservation(
        schema_version="1.0",
        buffer_id="buf-1",
        capacity=5,
        occupancy=2,
        occupants=[
            BufferOccupantSummary(unit_id="u-1", variant="sedan"),
            BufferOccupantSummary(unit_id="u-2", variant="suv"),
        ],
    )
    req1 = DecisionRequest(
        request_id="req-1",
        request_type="buffer_threshold",
        time_ns=1000,
        target_id="buf-1",
        observation=obs1,
    )

    obs2 = BufferObservation(
        schema_version="1.0",
        buffer_id="buf-2",
        capacity=5,
        occupancy=1,
        occupants=[BufferOccupantSummary(unit_id="u-3", variant="truck")],
    )
    req2 = DecisionRequest(
        request_id="req-2",
        request_type="buffer_threshold",
        time_ns=1000,
        target_id="buf-2",
        observation=obs2,
    )

    batch = DecisionBatch(
        batch_id="b-2",
        episode_id="ep-1",
        time_ns=1000,
        requests=[req1, req2],
    )

    # 1. Missing action for req2
    resp_missing = DecisionBatchResponse(
        batch_id="b-2",
        provenance=DecisionProvenance(episode_id="ep-1", batch_id="b-2"),
        actions=[BufferReorderAction(target_id="buf-1", new_order=["u-2", "u-1"])],
    )
    valid, diags = validate_decision_batch_response(batch, resp_missing)
    assert valid is False
    assert any(d.code == "MISSING_ACTION" and d.target_id == "buf-2" for d in diags)

    # 2. Unknown unit in action
    resp_unknown = DecisionBatchResponse(
        batch_id="b-2",
        provenance=DecisionProvenance(episode_id="ep-1", batch_id="b-2"),
        actions=[
            BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-999"]),
            BufferReorderAction(target_id="buf-2", new_order=["u-3"]),
        ],
    )
    valid, diags = validate_decision_batch_response(batch, resp_unknown)
    assert valid is False
    assert any(d.code == "UNKNOWN_UNIT" for d in diags)

    # 3. Duplicate units in action
    resp_dup = DecisionBatchResponse(
        batch_id="b-2",
        provenance=DecisionProvenance(episode_id="ep-1", batch_id="b-2"),
        actions=[
            BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-1"]),
            BufferReorderAction(target_id="buf-2", new_order=["u-3"]),
        ],
    )
    valid, diags = validate_decision_batch_response(batch, resp_dup)
    assert valid is False
    assert any(d.code == "DUPLICATE_UNIT" for d in diags)

    # 4. Conflicting actions: multiple actions for same target
    resp_conflict = DecisionBatchResponse(
        batch_id="b-2",
        provenance=DecisionProvenance(episode_id="ep-1", batch_id="b-2"),
        actions=[
            BufferReorderAction(target_id="buf-1", new_order=["u-2", "u-1"]),
            BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-2"]),
            BufferReorderAction(target_id="buf-2", new_order=["u-3"]),
        ],
    )
    valid, diags = validate_decision_batch_response(batch, resp_conflict)
    assert valid is False
    assert any(d.code == "CONFLICTING_ACTIONS" for d in diags)


def test_fifo_buffer_fallback_policy() -> None:
    obs = BufferObservation(
        schema_version="1.0",
        buffer_id="buf-1",
        capacity=5,
        occupancy=3,
        occupants=[
            BufferOccupantSummary(unit_id="u-3", variant="sedan", enter_time_ns=3000),
            BufferOccupantSummary(unit_id="u-1", variant="sedan", enter_time_ns=1000),
            BufferOccupantSummary(unit_id="u-2", variant="sedan", enter_time_ns=2000),
        ],
    )
    req = DecisionRequest(
        request_id="req-1",
        request_type="buffer_threshold",
        time_ns=3000,
        target_id="buf-1",
        observation=obs,
    )
    batch = DecisionBatch(
        batch_id="b-1",
        episode_id="ep-1",
        time_ns=3000,
        requests=[req],
    )

    policy = FifoBufferFallbackPolicy()
    actions = policy.generate_fallback_actions(batch)
    assert len(actions) == 1
    assert actions[0].target_id == "buf-1"
    # Fallback sorts by enter_time_ns: u-1 (1000), u-2 (2000), u-3 (3000)
    assert actions[0].new_order == ["u-1", "u-2", "u-3"]


def test_validate_decision_unrequested_target_and_immutability() -> None:
    obs = BufferObservation(
        schema_version="1.0",
        buffer_id="buf-1",
        capacity=5,
        occupancy=1,
        occupants=[BufferOccupantSummary(unit_id="u-1", variant="sedan")],
    )
    # Test frozen/immutability
    with pytest.raises(Exception):
        obs.occupancy = 10  # type: ignore

    req = DecisionRequest(
        request_id="req-1",
        time_ns=1000,
        target_id="buf-1",
        trigger_id="trig-1",
        observation=obs,
    )
    assert req.schema_version == "1.0"
    assert req.trigger_id == "trig-1"

    batch = DecisionBatch(
        batch_id="b-1",
        episode_id="ep-1",
        branch_id="counterfactual-1",
        time_ns=1000,
        requests=[req],
    )
    assert batch.branch_id == "counterfactual-1"

    # Response with an unrequested target (e.g. buf-unrequested)
    resp = DecisionBatchResponse(
        batch_id="b-1",
        provenance=DecisionProvenance(episode_id="ep-1", branch_id="counterfactual-1", batch_id="b-1"),
        actions=[
            BufferReorderAction(target_id="buf-1", new_order=["u-1"]),
            BufferReorderAction(target_id="buf-unrequested", new_order=["u-99"]),
        ],
    )
    valid, diags = validate_decision_batch_response(batch, resp)
    assert valid is False
    assert any(d.code == "UNREQUESTED_TARGET" for d in diags)



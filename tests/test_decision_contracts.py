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


def test_versioned_action_schemas_and_extra_forbidden() -> None:
    from industrialsim.decisions import (
        RoutingAction,
        DispatchAction,
        MachineModeAction,
        MaintenanceAction,
        ReconfigurationAction,
        WorkerReassignmentAction,
        QualityControlAction,
        RoutingObservation,
        DispatchObservation,
        MachineObservation,
        StrategicObservation,
    )

    # 1. RoutingAction
    route_act = RoutingAction(
        target_id="unit-1",
        route_id="r-main",
        unit_id="unit-1",
    )
    assert route_act.action_type == "routing"
    assert route_act.schema_version == "1.0"
    assert route_act.target_id == "unit-1"
    assert route_act.route_id == "r-main"

    # 2. DispatchAction
    dispatch_act = DispatchAction(
        target_id="order-1",
        route_id="r-main",
        vehicle_id="veh-1",
    )
    assert dispatch_act.action_type == "dispatch"
    assert dispatch_act.target_id == "order-1"
    assert dispatch_act.vehicle_id == "veh-1"

    # 3. MachineModeAction
    mode_act = MachineModeAction(
        target_id="mach-1",
        mode="eco",
    )
    assert mode_act.action_type == "machine_mode"
    assert mode_act.target_id == "mach-1"
    assert mode_act.mode == "eco"

    # 4. MaintenanceAction
    maint_act = MaintenanceAction(
        target_id="mach-1",
        trigger_maintenance=True,
    )
    assert maint_act.action_type == "maintenance"
    assert maint_act.target_id == "mach-1"
    assert maint_act.trigger_maintenance is True

    # 5. Strategic Actions: Reconfiguration, WorkerReassignment, QualityControl
    reconfig_act = ReconfigurationAction(
        target_id="st-1",
        configuration={"tooling": "tool-b"},
        duration_ns=30_000_000,
        cost=150.0,
    )
    assert reconfig_act.action_type == "reconfiguration"
    assert reconfig_act.duration_ns == 30_000_000
    assert reconfig_act.cost == 150.0

    worker_act = WorkerReassignmentAction(
        target_id="worker-1",
        assigned_station_id="st-2",
        qualifications=["welding"],
        duration_ns=10_000_000,
        cost=50.0,
    )
    assert worker_act.action_type == "worker_reassignment"
    assert worker_act.duration_ns == 10_000_000
    assert worker_act.cost == 50.0

    quality_act = QualityControlAction(
        target_id="st-insp",
        inspection_intensity=0.95,
        sampling_rate=0.5,
        release_threshold=0.8,
        duration_ns=5_000_000,
        cost=25.0,
    )
    assert quality_act.action_type == "quality_control"
    assert quality_act.inspection_intensity == 0.95
    assert quality_act.sampling_rate == 0.5
    assert quality_act.release_threshold == 0.8
    assert quality_act.duration_ns == 5_000_000
    assert quality_act.cost == 25.0

    # Test extra="forbid" on all actions (cannot inject arbitrary attributes or latent quality state)
    with pytest.raises(Exception):
        RoutingAction(target_id="u-1", route_id="r-1", quality_state="nominal")  # type: ignore

    with pytest.raises(Exception):
        BufferReorderAction(target_id="buf-1", new_order=["u-1"], create_capacity=10)  # type: ignore

    with pytest.raises(Exception):
        MachineModeAction(target_id="m-1", mode="eco", bypass_safety_limit=True)  # type: ignore


def test_polymorphic_batch_response_serialization() -> None:
    from industrialsim.decisions import (
        RoutingAction,
        MachineModeAction,
    )

    resp = DecisionBatchResponse(
        batch_id="b-poly",
        provenance=DecisionProvenance(episode_id="ep-1", batch_id="b-poly"),
        actions=[
            BufferReorderAction(target_id="buf-1", new_order=["u-1"]),
            RoutingAction(target_id="u-2", route_id="r-2", unit_id="u-2"),
            MachineModeAction(target_id="mach-1", mode="fast"),
        ],
    )
    data = resp.model_dump()
    assert len(data["actions"]) == 3
    assert data["actions"][1]["action_type"] == "routing"
    assert data["actions"][2]["action_type"] == "machine_mode"

    restored = DecisionBatchResponse.model_validate(data)
    assert len(restored.actions) == 3
    assert isinstance(restored.actions[1], RoutingAction)
    assert isinstance(restored.actions[2], MachineModeAction)


def test_competing_resource_claims_rejected_as_batch() -> None:
    from industrialsim.decisions import DispatchAction, DispatchObservation

    obs1 = DispatchObservation(
        schema_version="1.0",
        order_id="order-1",
        unit_id="u-1",
        variant="sedan",
        source_node_id="buf-1",
        target_node_id="st-1",
        created_time_ns=1000,
    )
    req1 = DecisionRequest(
        request_id="req-1",
        request_type="dispatch",
        time_ns=1000,
        target_id="order-1",
        observation=obs1,
        action_schema="dispatch",
    )

    obs2 = DispatchObservation(
        schema_version="1.0",
        order_id="order-2",
        unit_id="u-2",
        variant="suv",
        source_node_id="buf-2",
        target_node_id="st-2",
        created_time_ns=1000,
    )
    req2 = DecisionRequest(
        request_id="req-2",
        request_type="dispatch",
        time_ns=1000,
        target_id="order-2",
        observation=obs2,
        action_schema="dispatch",
    )

    batch = DecisionBatch(
        batch_id="b-compete",
        episode_id="ep-1",
        time_ns=1000,
        requests=[req1, req2],
    )

    # Both dispatch actions simultaneously claim the same vehicle veh-1
    resp = DecisionBatchResponse(
        batch_id="b-compete",
        provenance=DecisionProvenance(episode_id="ep-1", batch_id="b-compete"),
        actions=[
            DispatchAction(target_id="order-1", route_id="r-1", vehicle_id="veh-1"),
            DispatchAction(target_id="order-2", route_id="r-2", vehicle_id="veh-1"),
        ],
    )

    valid, diags = validate_decision_batch_response(batch, resp)
    assert valid is False
    assert any(d.code == "COMPETING_RESOURCE_CLAIMS" for d in diags)


def test_strategic_actions_rejected_at_unsafe_decision_point() -> None:
    from industrialsim.decisions import ReconfigurationAction, StrategicObservation

    obs = StrategicObservation(
        schema_version="1.0",
        target_id="st-1",
        is_safe_point=False,  # NOT a safe decision point!
    )
    req = DecisionRequest(
        request_id="req-strat-1",
        request_type="strategic",
        time_ns=1000,
        target_id="st-1",
        is_safe_point=False,
        observation=obs,
        action_schema="reconfiguration",
    )
    batch = DecisionBatch(
        batch_id="b-strat",
        episode_id="ep-1",
        time_ns=1000,
        requests=[req],
    )

    resp = DecisionBatchResponse(
        batch_id="b-strat",
        provenance=DecisionProvenance(episode_id="ep-1", batch_id="b-strat"),
        actions=[
            ReconfigurationAction(
                target_id="st-1",
                configuration={"tooling": "tool-b"},
                duration_ns=10_000_000,
                cost=100.0,
            )
        ],
    )

    valid, diags = validate_decision_batch_response(batch, resp)
    assert valid is False
    assert any(d.code == "UNSAFE_DECISION_POINT" for d in diags)


def test_quality_actions_rejected_outside_configured_bounds() -> None:
    from industrialsim.decisions import (
        QualityControlAction,
        QualityControlBounds,
        StrategicObservation,
    )

    bounds = QualityControlBounds(
        min_inspection_intensity=0.5,
        max_inspection_intensity=0.98,
        min_sampling_rate=0.1,
        max_sampling_rate=1.0,
        min_release_threshold=0.2,
        max_release_threshold=0.8,
    )

    obs = StrategicObservation(
        schema_version="1.0",
        target_id="st-insp",
        is_safe_point=True,
        quality_control_bounds=bounds,
    )
    req = DecisionRequest(
        request_id="req-q-1",
        request_type="strategic",
        time_ns=1000,
        target_id="st-insp",
        is_safe_point=True,
        observation=obs,
        action_schema="quality_control",
    )
    batch = DecisionBatch(
        batch_id="b-q",
        episode_id="ep-1",
        time_ns=1000,
        requests=[req],
    )

    # 1. Inspection intensity out of bounds (1.5 > max 0.98)
    resp_bad_intensity = DecisionBatchResponse(
        batch_id="b-q",
        provenance=DecisionProvenance(episode_id="ep-1", batch_id="b-q"),
        actions=[
            QualityControlAction(
                target_id="st-insp",
                inspection_intensity=1.5,
                sampling_rate=0.5,
                release_threshold=0.5,
            )
        ],
    )
    valid, diags = validate_decision_batch_response(batch, resp_bad_intensity)
    assert valid is False
    assert any(d.code == "QUALITY_BOUNDS_EXCEEDED" for d in diags)

    # 2. Sampling rate out of bounds (0.05 < min 0.1)
    resp_bad_sampling = DecisionBatchResponse(
        batch_id="b-q",
        provenance=DecisionProvenance(episode_id="ep-1", batch_id="b-q"),
        actions=[
            QualityControlAction(
                target_id="st-insp",
                inspection_intensity=0.8,
                sampling_rate=0.05,
                release_threshold=0.5,
            )
        ],
    )
    valid, diags = validate_decision_batch_response(batch, resp_bad_sampling)
    assert valid is False
    assert any(d.code == "QUALITY_BOUNDS_EXCEEDED" for d in diags)

    # 3. Within bounds: should pass
    resp_ok = DecisionBatchResponse(
        batch_id="b-q",
        provenance=DecisionProvenance(episode_id="ep-1", batch_id="b-q"),
        actions=[
            QualityControlAction(
                target_id="st-insp",
                inspection_intensity=0.8,
                sampling_rate=0.5,
                release_threshold=0.5,
            )
        ],
    )
    valid, diags = validate_decision_batch_response(batch, resp_ok)
    assert valid is True
    assert len(diags) == 0


def test_fifo_earliest_due_date_tie_breaker() -> None:
    from industrialsim.decisions import (
        FifoBufferFallbackPolicy,
        BaselineDecisionProvider,
    )

    # Unit 1: entered at 1000, due at 50000
    # Unit 2: entered at 2000, due at 10000
    # Unit 3: entered at 2000, due at 5000  <- same enter_time_ns as Unit 2, but earlier due date!
    obs = BufferObservation(
        schema_version="1.0",
        buffer_id="buf-tie",
        capacity=5,
        occupancy=3,
        occupants=[
            BufferOccupantSummary(unit_id="u-1", variant="sedan", enter_time_ns=1000, due_date_ns=50000),
            BufferOccupantSummary(unit_id="u-2", variant="sedan", enter_time_ns=2000, due_date_ns=10000),
            BufferOccupantSummary(unit_id="u-3", variant="sedan", enter_time_ns=2000, due_date_ns=5000),
        ],
    )
    req = DecisionRequest(
        request_id="req-tie",
        request_type="buffer_threshold",
        time_ns=2000,
        target_id="buf-tie",
        observation=obs,
        action_schema="buffer_reorder",
    )
    batch = DecisionBatch(
        batch_id="b-tie",
        episode_id="ep-1",
        time_ns=2000,
        requests=[req],
    )

    policy = FifoBufferFallbackPolicy()
    actions = policy.generate_fallback_actions(batch)
    assert len(actions) == 1
    # u-1 is earliest enter_time (1000). Between u-2 and u-3 (both 2000), u-3 has earlier due_date (5000 vs 10000)
    assert actions[0].new_order == ["u-1", "u-3", "u-2"]

    # Test BaselineDecisionProvider produces the same result
    provider = BaselineDecisionProvider()
    resp = provider.decide(batch)
    assert len(resp.actions) == 1
    reorder_act = resp.actions[0]
    assert isinstance(reorder_act, BufferReorderAction)
    assert reorder_act.new_order == ["u-1", "u-3", "u-2"]


def test_baseline_decision_provider_routing_dispatch_machine() -> None:
    from industrialsim.decisions import (
        BaselineDecisionProvider,
        RoutingObservation,
        RouteSummaryObservation,
        RoutingAction,
        DispatchObservation,
        VehicleSummaryObservation,
        DispatchAction,
        MachineObservation,
        MaintenanceAction,
        MachineModeAction,
    )

    provider = BaselineDecisionProvider()

    # 1. Routing decision: should select shortest admissible route
    routing_obs = RoutingObservation(
        schema_version="1.0",
        unit_id="u-1",
        variant="sedan",
        current_node_id="st-1",
        candidate_routes=[
            RouteSummaryObservation(
                route_id="r-long",
                source_node_id="st-1",
                target_node_id="st-2a",
                transit_time_ns=30_000_000,
                is_admissible=True,
            ),
            RouteSummaryObservation(
                route_id="r-short",
                source_node_id="st-1",
                target_node_id="st-2b",
                transit_time_ns=10_000_000,
                is_admissible=True,
            ),
            RouteSummaryObservation(
                route_id="r-inadmissible",
                source_node_id="st-1",
                target_node_id="st-2c",
                transit_time_ns=5_000_000,
                is_admissible=False,  # cannot select inadmissible route
            ),
        ],
    )
    req_route = DecisionRequest(
        request_id="req-route-1",
        request_type="routing",
        time_ns=1000,
        target_id="u-1",
        observation=routing_obs,
        action_schema="routing",
    )

    # 2. Dispatch decision: should select shortest admissible route and nearest vehicle
    dispatch_obs = DispatchObservation(
        schema_version="1.0",
        order_id="order-1",
        unit_id="u-2",
        variant="sedan",
        source_node_id="buf-1",
        target_node_id="st-3",
        created_time_ns=1000,
        candidate_routes=[
            RouteSummaryObservation(
                route_id="r-d1",
                source_node_id="buf-1",
                target_node_id="st-3",
                transit_time_ns=20_000_000,
                is_admissible=True,
            ),
        ],
        available_vehicles=[
            VehicleSummaryObservation(
                vehicle_id="veh-far",
                location="sink",
                speed_multiplier=1.0,
                distance_to_pickup_ns=50_000_000,
            ),
            VehicleSummaryObservation(
                vehicle_id="veh-near",
                location="st-2",
                speed_multiplier=1.0,
                distance_to_pickup_ns=5_000_000,
            ),
        ],
    )
    req_dispatch = DecisionRequest(
        request_id="req-disp-1",
        request_type="dispatch",
        time_ns=1000,
        target_id="order-1",
        observation=dispatch_obs,
        action_schema="dispatch",
    )

    # 3. Machine decision: health <= threshold -> triggers maintenance
    mach_obs_degraded = MachineObservation(
        schema_version="1.0",
        machine_id="mach-degraded",
        health=0.25,  # <= threshold 0.3
        operating_mode="nominal",
        available_modes=["nominal", "eco", "fast"],
        maintenance_policy_summary={"health_threshold": 0.3},
    )
    req_maint = DecisionRequest(
        request_id="req-m-1",
        request_type="machine",
        time_ns=1000,
        target_id="mach-degraded",
        observation=mach_obs_degraded,
        action_schema="maintenance",
    )

    # 4. Machine decision: healthy machine -> nominal mode
    mach_obs_healthy = MachineObservation(
        schema_version="1.0",
        machine_id="mach-healthy",
        health=0.85,
        operating_mode="nominal",
        available_modes=["nominal", "eco", "fast"],
        maintenance_policy_summary={"health_threshold": 0.3},
    )
    req_mode = DecisionRequest(
        request_id="req-m-2",
        request_type="machine",
        time_ns=1000,
        target_id="mach-healthy",
        observation=mach_obs_healthy,
        action_schema="machine_mode",
    )

    batch = DecisionBatch(
        batch_id="b-mixed",
        episode_id="ep-1",
        time_ns=1000,
        requests=[req_route, req_dispatch, req_maint, req_mode],
    )

    resp = provider.decide(batch)
    assert len(resp.actions) == 4

    # Check routing action: chose r-short
    route_act = next(a for a in resp.actions if isinstance(a, RoutingAction))
    assert route_act.target_id == "u-1"
    assert route_act.route_id == "r-short"

    # Check dispatch action: chose r-d1 and veh-near
    disp_act = next(a for a in resp.actions if isinstance(a, DispatchAction))
    assert disp_act.target_id == "order-1"
    assert disp_act.route_id == "r-d1"
    assert disp_act.vehicle_id == "veh-near"

    # Check maintenance action: triggered for degraded machine
    maint_act = next(a for a in resp.actions if a.target_id == "mach-degraded")
    assert isinstance(maint_act, MaintenanceAction)
    assert maint_act.trigger_maintenance is True

    # Check healthy machine action: mode set to nominal
    mode_act = next(a for a in resp.actions if a.target_id == "mach-healthy")
    assert isinstance(mode_act, MachineModeAction)
    assert mode_act.mode == "nominal"



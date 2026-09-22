from __future__ import annotations

import numpy as np
import pytest
from ruamel.yaml import YAML

from industrialsim.application import EpisodeEngine
from industrialsim.config import SimulationConfig
from industrialsim.decisions import (
    BufferObservation,
    BufferOccupantSummary,
    BufferReorderAction,
    DecisionBatch,
    DecisionRequest,
    MachineModeAction,
    MachineObservation,
    MaintenanceAction,
    QualityControlAction,
    QualityControlBounds,
    RouteSummaryObservation,
    RoutingAction,
    RoutingObservation,
    StrategicObservation,
)
from industrialsim.forecasting.baselines import (
    ExponentialSmoothingForecaster,
    MovingAverageForecaster,
)
from industrialsim.forecasting.hierarchical_provider import HierarchicalPredictiveProvider
from industrialsim.forecasting.timesfm_adapter import TimesFM3Adapter


def test_hierarchical_provider_decisions() -> None:
    adapter = TimesFM3Adapter()
    provider = HierarchicalPredictiveProvider(
        forecaster=adapter,
        horizon=16,
        future_plan_entries=[
            {"release_time_ns": 30_000_000_000, "quantity": 5},
            {"release_time_ns": 60_000_000_000, "quantity": 10},
        ],
    )

    # 1. Makro request: Strategic Safe-Point with QualityControl bounds
    strat_obs = StrategicObservation(
        schema_version="1.0",
        target_id="st-qc-1",
        allowed_actions=["quality_control"],
        quality_control_bounds=QualityControlBounds(
            min_inspection_intensity=0.5,
            max_inspection_intensity=1.0,
            min_sampling_rate=0.2,
            max_sampling_rate=1.0,
            min_release_threshold=0.0,
            max_release_threshold=0.9,
        ),
        aggregate_metrics={"wip": 12.0},
    )
    strat_req = DecisionRequest(
        request_id="req-strat-1",
        request_type="strategic",
        time_ns=10_000_000_000,
        target_id="st-qc-1",
        observation=strat_obs,
        action_schema="strategic",
    )

    # 2. Meso request: Routing at source
    route_obs = RoutingObservation(
        schema_version="1.0",
        unit_id="unit-1",
        variant="compact-express",
        current_node_id="src-raw",
        due_date_ns=100_000_000_000,
        candidate_routes=[
            RouteSummaryObservation(
                route_id="r-src-b1",
                source_node_id="src-raw",
                target_node_id="st-body-1",
                transit_time_ns=5_000_000_000,
                current_occupancy=4,
                is_admissible=True,
            ),
            RouteSummaryObservation(
                route_id="r-src-b2",
                source_node_id="src-raw",
                target_node_id="st-body-2",
                transit_time_ns=5_000_000_000,
                current_occupancy=1,
                is_admissible=True,
            ),
        ],
        aggregate_metrics={"wip": 12.0},
    )
    route_req = DecisionRequest(
        request_id="req-route-1",
        request_type="routing",
        time_ns=10_000_000_000,
        target_id="src-raw",
        observation=route_obs,
        action_schema="routing",
    )

    # 3. Mikro request: Buffer reordering
    buf_obs = BufferObservation(
        schema_version="1.0",
        buffer_id="buf-body-paint",
        capacity=8,
        occupancy=2,
        occupants=[
            BufferOccupantSummary(
                unit_id="unit-heavy",
                variant="luxury-suv",
                due_date_ns=500_000_000_000,
            ),
            BufferOccupantSummary(
                unit_id="unit-express",
                variant="compact-express",
                due_date_ns=30_000_000_000,
            ),
        ],
        aggregate_metrics={"wip": 12.0},
    )
    buf_req = DecisionRequest(
        request_id="req-buf-1",
        request_type="buffer_threshold",
        time_ns=10_000_000_000,
        target_id="buf-body-paint",
        observation=buf_obs,
        action_schema="buffer_reorder",
    )

    # 4. Mikro request: Degraded machine maintenance
    mach_obs = MachineObservation(
        schema_version="1.0",
        machine_id="m-paint-robot-1",
        health=0.32,
        aggregate_metrics={"wip": 12.0},
    )
    mach_req = DecisionRequest(
        request_id="req-mach-1",
        request_type="machine",
        time_ns=10_000_000_000,
        target_id="m-paint-robot-1",
        observation=mach_obs,
        action_schema="maintenance",
    )

    batch = DecisionBatch(
        batch_id="batch-test-hierarchical",
        episode_id="ep-test",
        time_ns=10_000_000_000,
        requests=[strat_req, route_req, buf_req, mach_req],
    )

    response = provider.decide(batch)
    assert len(response.actions) == 4
    assert response.provenance.provider_id == "hierarchical_forecaster"

    # Validate action types
    qc_act = next(a for a in response.actions if isinstance(a, QualityControlAction))
    assert qc_act.target_id == "st-qc-1"
    assert qc_act.inspection_intensity is not None

    route_act = next(a for a in response.actions if isinstance(a, RoutingAction))
    assert route_act.target_id == "src-raw"
    assert route_act.route_id in ("r-src-b1", "r-src-b2")
    # Low occupancy route (r-src-b2) should be selected
    assert route_act.route_id == "r-src-b2"

    buf_act = next(a for a in response.actions if isinstance(a, BufferReorderAction))
    assert buf_act.target_id == "buf-body-paint"
    # Express unit should be advanced ahead of heavy unit
    assert buf_act.new_order == ["unit-express", "unit-heavy"]

    maint_act = next(a for a in response.actions if isinstance(a, MaintenanceAction))
    assert maint_act.target_id == "m-paint-robot-1"
    assert maint_act.trigger_maintenance is True


def test_hierarchical_provider_simulation_run() -> None:
    yaml = YAML(typ="safe")
    with open("examples/hierarchical_forecasting_plant.yaml") as f:
        data = yaml.load(f)
    cfg = SimulationConfig.model_validate(data)

    adapter = TimesFM3Adapter()
    plan_entries = [p.model_dump() for p in cfg.production_plan]
    provider = HierarchicalPredictiveProvider(
        forecaster=adapter,
        future_plan_entries=plan_entries,
    )

    engine = EpisodeEngine.create(cfg, decision_provider=provider)
    summary = engine.run()

    assert not summary.is_deadlocked
    assert not summary.is_aborted
    assert summary.raw_metrics["good_output"] == 45
    assert len(summary.decision_batches) > 0


def test_exponential_smoothing_forecaster() -> None:
    forecaster = ExponentialSmoothingForecaster(alpha=0.3, beta=0.1, phi=0.95)

    # Empty and single-element tests
    res_empty = forecaster.forecast({"wip": np.array([])}, horizon=16)
    assert res_empty.point_forecast["wip"].shape == (16,)
    assert np.all(res_empty.point_forecast["wip"] == 0.0)

    res_single = forecaster.forecast({"wip": np.array([42.0])}, horizon=16)
    assert res_single.point_forecast["wip"].shape == (16,)
    assert np.all(res_single.point_forecast["wip"] == 42.0)

    # Linear series test over horizon 128
    series = np.array([10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0])
    res = forecaster.forecast({"wip": series}, horizon=128)
    preds = res.point_forecast["wip"]
    assert len(preds) == 128
    # With positive trend and phi=0.95, first step should exceed last observed value
    assert preds[0] > 24.0
    # Damped trend should be strictly non-negative and eventually level off
    assert np.all(preds >= 0.0)
    # Quantiles monotonicity
    q_mat = res.quantile_forecast["wip"]
    assert q_mat.shape == (128, len(forecaster.quantiles))
    for t in range(128):
        assert q_mat[t, 0] <= q_mat[t, 1] <= q_mat[t, 2] <= q_mat[t, 3] <= q_mat[t, 4]


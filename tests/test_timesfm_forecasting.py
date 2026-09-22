from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pytest

from industrialsim.application import run_episode
from industrialsim.decisions import (
    BufferObservation,
    BufferOccupantSummary,
    BufferReorderAction,
    DecisionBatch,
    DecisionRequest,
    MachineObservation,
    MaintenanceAction,
    RoutingAction,
    RoutingObservation,
    RouteSummaryObservation,
)
from industrialsim.forecasting.baselines import (
    LinearTrendCovariateForecaster,
    MovingAverageForecaster,
    NaiveLastValueForecaster,
)
from industrialsim.forecasting.benchmark import (
    load_telemetry_series,
    run_offline_benchmark,
)
from industrialsim.forecasting.experiment import run_counterfactual_experiment
from industrialsim.forecasting.metrics import (
    continuous_ranked_probability_score,
    evaluate_forecast,
    mean_absolute_error,
    pinball_loss,
    root_mean_squared_error,
    weighted_absolute_percentage_error,
    weighted_quantile_loss,
)
from industrialsim.forecasting.protocol import ForecastResult
from industrialsim.forecasting.provider import PredictiveDecisionProvider
from industrialsim.forecasting.timesfm_adapter import (
    DEFAULT_QUANTILES,
    DeterministicTimesFM3Engine,
    TimesFM3Adapter,
)


def test_forecast_result_container() -> None:
    point = {"wip": np.array([10.0, 11.0, 12.0])}
    quantiles_data = np.tile(np.array([10.0, 11.0, 12.0])[:, None], (1, 9))
    # Spread out quantiles
    for i in range(9):
        quantiles_data[:, i] += (i - 4) * 0.5
    quantiles_dict = {"wip": quantiles_data}

    res = ForecastResult(
        point_forecast=point,
        quantile_forecast=quantiles_dict,
        quantiles=DEFAULT_QUANTILES,
    )

    assert len(res.get_mean("wip")) == 3
    assert np.allclose(res.get_mean("wip"), [10.0, 11.0, 12.0])
    q50 = res.get_quantile("wip", 0.5)
    assert np.allclose(q50, [10.0, 11.0, 12.0])
    q90 = res.get_quantile("wip", 0.9)
    assert q90[0] > q50[0]

    with pytest.raises(KeyError):
        res.get_mean("unknown")
    with pytest.raises(KeyError):
        res.get_quantile("unknown", 0.5)


def test_timesfm3_adapter_dimensions_and_properties() -> None:
    forecaster = TimesFM3Adapter(patch_len=32, horizon_len=64)

    # 128 timesteps of past data
    past_targets = {
        "wip": np.linspace(5.0, 20.0, 128),
        "machines_failed": np.zeros(128),
    }
    past_covariates = {
        "scrap": np.ones(128) * 0.5,
    }
    future_covariates = {
        "planned_load": np.linspace(1.0, 3.0, 64),
    }

    result = forecaster.forecast(
        past_targets=past_targets,
        past_covariates=past_covariates,
        future_covariates=future_covariates,
        horizon=64,
    )

    assert "wip" in result.point_forecast
    assert len(result.point_forecast["wip"]) == 64
    assert result.quantile_forecast["wip"].shape == (64, 9)
    # Physical count should remain non-negative
    assert np.all(result.point_forecast["wip"] >= 0.0)
    assert np.all(result.quantile_forecast["wip"] >= 0.0)


def test_timesfm3_lookahead_covariate_effect() -> None:
    engine = DeterministicTimesFM3Engine(patch_len=32)

    past = {"wip": np.full(64, 10.0)}

    # High future load spike vs flat future load
    high_future = {"planned_load": np.array([10.0] * 32 + [50.0] * 32)}
    flat_future = {"planned_load": np.full(64, 10.0)}

    res_high = engine.forecast(past_targets=past, future_covariates=high_future, horizon=64)
    res_flat = engine.forecast(past_targets=past, future_covariates=flat_future, horizon=64)

    # Lookahead: high future covariate should raise predicted WIP in the spike window
    mean_high = res_high.get_mean("wip")
    mean_flat = res_flat.get_mean("wip")
    assert np.mean(mean_high[32:]) > np.mean(mean_flat[32:])


def test_probabilistic_metrics() -> None:
    y_true = np.array([10.0, 12.0, 14.0])
    y_pred = np.array([10.0, 13.0, 13.0])

    mae = mean_absolute_error(y_true, y_pred)
    assert np.isclose(mae, 2.0 / 3.0)

    rmse = root_mean_squared_error(y_true, y_pred)
    assert np.isclose(rmse, np.sqrt(2.0 / 3.0))

    wape = weighted_absolute_percentage_error(y_true, y_pred)
    assert np.isclose(wape, 2.0 / 36.0)

    # Pinball loss
    loss_q5 = pinball_loss(np.array([10.0]), np.array([12.0]), 0.5)
    assert np.isclose(loss_q5[0], 1.0)

    # CRPS for identical predictions should be close to 0
    q_identical = np.tile(y_true[:, None], (1, 9))
    crps_val = continuous_ranked_probability_score(y_true, q_identical, DEFAULT_QUANTILES)
    assert np.isclose(crps_val, 0.0)


def test_baseline_forecasters() -> None:
    past = {"wip": np.array([5.0, 6.0, 7.0, 8.0, 9.0, 10.0])}
    horizon = 16

    ma = MovingAverageForecaster(window_size=4)
    res_ma = ma.forecast(past, horizon=horizon)
    assert len(res_ma.get_mean("wip")) == horizon
    assert np.isclose(res_ma.get_mean("wip")[0], 8.5)

    lin = LinearTrendCovariateForecaster()
    res_lin = lin.forecast(past, horizon=horizon)
    assert len(res_lin.get_mean("wip")) == horizon
    # Linear slope of [5,6,7,8,9,10] is 1.0 -> next value should be ~11.0
    assert np.isclose(res_lin.get_mean("wip")[0], 11.0, atol=0.2)

    naive = NaiveLastValueForecaster()
    res_naive = naive.forecast(past, horizon=horizon)
    assert np.allclose(res_naive.get_mean("wip"), 10.0)


def test_predictive_decision_provider(tmp_path: Path) -> None:
    forecaster = TimesFM3Adapter(patch_len=32)
    provider = PredictiveDecisionProvider(
        forecaster=forecaster,
        provider_id="test_provider",
        maintenance_risk_threshold=0.5,
    )

    batch = DecisionBatch(
        batch_id="b-001",
        episode_id="ep-test",
        time_ns=30_000_000_000,
        requests=[
            DecisionRequest(
                request_id="req-maint",
                time_ns=30_000_000_000,
                target_id="m-welder-1",
                action_schema="maintenance",
                observation=MachineObservation(
                    machine_id="m-welder-1",
                    health=0.25,  # severely degraded
                ),
            ),
            DecisionRequest(
                request_id="req-routing",
                time_ns=30_000_000_000,
                target_id="u-001",
                action_schema="routing",
                observation=RoutingObservation(
                    unit_id="u-001",
                    variant="sedan",
                    current_node_id="src-raw",
                    candidate_routes=[
                        RouteSummaryObservation(
                            route_id="r-fast",
                            source_node_id="src-raw",
                            target_node_id="st-weld-fast",
                            transit_time_ns=5_000_000_000,
                            current_occupancy=4,
                        ),
                        RouteSummaryObservation(
                            route_id="r-robust",
                            source_node_id="src-raw",
                            target_node_id="st-weld-robust",
                            transit_time_ns=5_000_000_000,
                            current_occupancy=0,
                        ),
                    ],
                ),
            ),
            DecisionRequest(
                request_id="req-reorder",
                time_ns=30_000_000_000,
                target_id="buf-intermediate",
                action_schema="buffer_reorder",
                observation=BufferObservation(
                    buffer_id="buf-intermediate",
                    capacity=8,
                    occupancy=2,
                    occupants=[
                        BufferOccupantSummary(unit_id="u-late", variant="sedan", due_date_ns=100),
                        BufferOccupantSummary(unit_id="u-early", variant="sedan", due_date_ns=50),
                    ],
                ),
            ),
        ],
    )

    resp = provider.decide(batch)
    assert resp.batch_id == "b-001"
    assert len(resp.actions) == 3

    # Maintenance action
    maint_act = next(a for a in resp.actions if isinstance(a, MaintenanceAction))
    assert maint_act.target_id == "m-welder-1"
    assert maint_act.trigger_maintenance is True

    # Routing action should choose less congested route
    route_act = next(a for a in resp.actions if isinstance(a, RoutingAction))
    assert route_act.route_id == "r-robust"

    # Reorder action should prioritize earlier due date
    reorder_act = next(a for a in resp.actions if isinstance(a, BufferReorderAction))
    assert reorder_act.new_order == ["u-early", "u-late"]


def test_offline_benchmark_and_counterfactual_pipeline(tmp_path: Path) -> None:
    # 1. Run quick episode with forecasting benchmark config
    cfg_path = "examples/forecasting_benchmark_plant.yaml"
    out_dir = tmp_path / "bench_run"

    summary = run_episode(cfg_path, output_dir=out_dir)
    assert summary.status == "completed"

    # 2. Check telemetry was written
    telemetry_dir = out_dir / "telemetry"
    series = load_telemetry_series(telemetry_dir)
    assert "wip" in series
    assert len(series["wip"]) >= 64

    # 3. Run offline benchmark
    report = run_offline_benchmark(
        telemetry_dir=telemetry_dir,
        context_len=32,
        horizon=16,
        stride=16,
        target_names=("wip", "good_output", "machines_busy"),
        covariate_names=("scrap", "downtime_ns"),
    )

    assert "TimesFM-3 (Multivariate)" in report["models"]
    assert "TimesFM-3 (Univariate)" in report["models"]
    assert "Moving Average (w=16)" in report["models"]
    for m_name, m_res in report["models"].items():
        assert "mae" in m_res["overall"]
        assert "crps" in m_res["overall"]
        assert "mean_wql" in m_res["overall"]

    # 4. Run counterfactual experiment
    exp_out = tmp_path / "exp_run"
    exp_report = run_counterfactual_experiment(config_path=cfg_path, output_dir=exp_out)
    assert "Branch_A_Reactive_Baseline" in exp_report["branches"]
    assert "Branch_B_TimesFM3_Predictive" in exp_report["branches"]
    assert "Branch_C_MovingAverage_Baseline" in exp_report["branches"]

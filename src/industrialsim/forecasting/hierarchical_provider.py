from __future__ import annotations

import logging
from typing import Any, Sequence
import numpy as np

from industrialsim.decisions import (
    BufferObservation,
    BufferOccupantSummary,
    BufferReorderAction,
    DecisionAction,
    DecisionBatch,
    DecisionBatchResponse,
    DecisionProvenance,
    DecisionProvider,
    MachineModeAction,
    MachineObservation,
    MaintenanceAction,
    QualityControlAction,
    RoutingAction,
    RoutingObservation,
    StrategicObservation,
)
from industrialsim.forecasting.protocol import TimeSeriesForecaster

logger = logging.getLogger(__name__)


class HierarchicalPredictiveProvider(DecisionProvider):
    """
    Multi-hierarchy closed-loop DecisionProvider coordinating actions across three levels:
    1. Makro (Plant-Level): Evaluates aggregate WIP & throughput to adjust plant modes
       and quality inspection intensity at strategic safe points.
    2. Meso (Area-Level): Forecasts inter-area buffer congestion to dynamically route
       material between parallel shop lines.
    3. Mikro (Station & Buffer Level): Evaluates quantile machine health forecasts to schedule
       proactive maintenance, and balances delivery deadlines with surge pressures to
       reorder intermediate buffer queues.
    """

    def __init__(
        self,
        forecaster: TimeSeriesForecaster,
        provider_id: str = "hierarchical_forecaster",
        model_id: str = "timesfm-3",
        horizon: int = 32,
        maintenance_risk_threshold: float = 0.65,
        wip_surge_threshold: float = 0.20,
        future_plan_entries: list[dict[str, Any]] | None = None,
    ) -> None:
        self.forecaster = forecaster
        self.provider_id = provider_id
        self.model_id = model_id
        self.horizon = horizon
        self.maintenance_risk_threshold = maintenance_risk_threshold
        self.wip_surge_threshold = wip_surge_threshold
        self.future_plan_entries = future_plan_entries or []

        # Time series history storage
        self._history_time_ns: list[int] = []
        self._history_wip: list[float] = []
        self._history_failures: list[float] = []
        self._history_buffer_occupancy: dict[str, list[float]] = {}
        self._history_machine_health: dict[str, list[float]] = {}

    def update_telemetry_history(
        self,
        time_ns: int,
        metrics: dict[str, Any],
        buffer_levels: dict[str, float] | None = None,
        machine_healths: dict[str, float] | None = None,
    ) -> None:
        """Feed external telemetry snapshot into the provider history."""
        self._history_time_ns.append(time_ns)
        self._history_wip.append(float(metrics.get("wip", 0)))
        self._history_failures.append(float(metrics.get("machines_failed", 0)))

        if buffer_levels:
            for b_id, occ in buffer_levels.items():
                if b_id not in self._history_buffer_occupancy:
                    self._history_buffer_occupancy[b_id] = []
                self._history_buffer_occupancy[b_id].append(float(occ))

        if machine_healths:
            for m_id, h in machine_healths.items():
                if m_id not in self._history_machine_health:
                    self._history_machine_health[m_id] = []
                self._history_machine_health[m_id].append(float(h))

    def _build_future_covariates(self, current_time_ns: int) -> dict[str, np.ndarray]:
        """Construct planned production release and cumulative load signals."""
        if not self.future_plan_entries:
            return {
                "planned_release_rate": np.ones(self.horizon, dtype=np.float64),
                "planned_cumulative_load": np.arange(1, self.horizon + 1, dtype=np.float64),
            }

        step_dt_ns = 30_000_000_000
        time_grid = current_time_ns + np.arange(1, self.horizon + 1) * step_dt_ns

        planned_quantities = np.zeros(self.horizon, dtype=np.float64)
        for entry in self.future_plan_entries:
            rel_t = int(entry.get("release_time_ns", entry.get("release_time", 0)))
            qty = float(entry.get("quantity", 1))
            if current_time_ns <= rel_t <= time_grid[-1]:
                idx = int((rel_t - current_time_ns) // step_dt_ns)
                if 0 <= idx < self.horizon:
                    planned_quantities[idx] += qty

        return {
            "planned_release_rate": planned_quantities,
            "planned_cumulative_load": np.cumsum(planned_quantities),
        }

    def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
        actions: list[DecisionAction] = []
        current_time_ns = batch.time_ns

        # Ingest state from requests in this batch
        batch_metrics: dict[str, Any] = {}
        for req in batch.requests:
            obs = req.observation
            if isinstance(obs, BufferObservation):
                if obs.buffer_id not in self._history_buffer_occupancy:
                    self._history_buffer_occupancy[obs.buffer_id] = []
                self._history_buffer_occupancy[obs.buffer_id].append(float(obs.occupancy))
                batch_metrics.update(obs.aggregate_metrics)
            elif isinstance(obs, MachineObservation):
                if obs.machine_id not in self._history_machine_health:
                    self._history_machine_health[obs.machine_id] = []
                self._history_machine_health[obs.machine_id].append(float(obs.health))
                batch_metrics.update(obs.aggregate_metrics)
            elif isinstance(obs, (RoutingObservation, StrategicObservation)):
                batch_metrics.update(obs.aggregate_metrics)

        self._history_time_ns.append(current_time_ns)
        self._history_wip.append(float(batch_metrics.get("wip", 1.0)))
        self._history_failures.append(float(batch_metrics.get("machines_failed", 0.0)))

        # Prepare forecast inputs
        past_targets: dict[str, np.ndarray] = {
            "wip": np.array(self._history_wip, dtype=np.float64),
            "machines_failed": np.array(self._history_failures, dtype=np.float64),
        }
        for b_id, vals in self._history_buffer_occupancy.items():
            past_targets[f"buffer_load_{b_id}"] = np.array(vals, dtype=np.float64)
        for m_id, vals in self._history_machine_health.items():
            past_targets[f"machine_health_{m_id}"] = np.array(vals, dtype=np.float64)

        past_covariates: dict[str, np.ndarray] = {
            "wip": past_targets["wip"],
        }
        future_covariates = self._build_future_covariates(current_time_ns)

        # Run hierarchical forecast
        forecast = self.forecaster.forecast(
            past_targets=past_targets,
            past_covariates=past_covariates,
            future_covariates=future_covariates,
            horizon=self.horizon,
        )

        # Evaluate forecast signals
        predicted_wip = (
            float(np.mean(forecast.get_mean("wip")[:8]))
            if "wip" in forecast.point_forecast
            else (self._history_wip[-1] if self._history_wip else 1.0)
        )
        recent_wip = self._history_wip[-1] if self._history_wip else 1.0
        surge_level = max(0.0, predicted_wip - recent_wip)
        is_surge_expected = surge_level > (recent_wip * self.wip_surge_threshold)

        handled_targets: set[str] = set()

        for req in batch.requests:
            if req.target_id in handled_targets:
                continue
            act_count_before = len(actions)

            # =================================================================
            # 1. MAKRO-EBENE: Strategische Safe-Points (MachineMode & QualityControl)
            # =================================================================
            if req.action_schema == "strategic" or isinstance(req.observation, StrategicObservation):
                obs = req.observation
                if isinstance(obs, StrategicObservation) and not obs.is_safe_point:
                    continue
                allowed_actions = obs.allowed_actions if isinstance(obs, StrategicObservation) else []

                # A. Quality Control adaptation
                if "quality_control" in allowed_actions or (
                    isinstance(obs, StrategicObservation) and obs.quality_control_bounds is not None
                ):
                    bounds = obs.quality_control_bounds if isinstance(obs, StrategicObservation) else None
                    if bounds:
                        if is_surge_expected:
                            # During surges, adjust sampling towards lower bound to prevent line starvation
                            sampling = float(bounds.min_sampling_rate)
                            intensity = float(bounds.min_inspection_intensity)
                        else:
                            # In nominal/calm conditions, maintain thorough inspection
                            sampling = float(bounds.max_sampling_rate)
                            intensity = float(bounds.max_inspection_intensity)

                        actions.append(
                            QualityControlAction(
                                target_id=req.target_id,
                                inspection_intensity=intensity,
                                sampling_rate=sampling,
                                release_threshold=bounds.max_release_threshold,
                            )
                        )
                    else:
                        actions.append(
                            QualityControlAction(
                                target_id=req.target_id,
                                inspection_intensity=0.9,
                                sampling_rate=0.5,
                            )
                        )

                # B. Machine Mode switching at safe point
                elif "machine_mode" in allowed_actions or req.target_id.startswith("st-paint") or req.target_id.startswith("m-"):
                    mode = "boost" if is_surge_expected else "nominal"
                    actions.append(
                        MachineModeAction(
                            target_id=req.target_id,
                            mode=mode,
                        )
                    )

                else:
                    # Default mode action if permitted
                    actions.append(
                        MachineModeAction(
                            target_id=req.target_id,
                            mode="boost" if is_surge_expected else "nominal",
                        )
                    )

            # =================================================================
            # 2. MESO-EBENE: Inter-Area Routing
            # =================================================================
            elif req.action_schema == "routing" or isinstance(req.observation, RoutingObservation):
                obs = req.observation
                candidate_routes = (
                    obs.candidate_routes if isinstance(obs, RoutingObservation) else []
                )
                admissible_routes = [r for r in candidate_routes if r.is_admissible]

                if admissible_routes:
                    best_route = admissible_routes[0]
                    lowest_projected_load = float("inf")

                    for route in admissible_routes:
                        target_node = route.target_node_id
                        buf_key = f"buffer_load_{target_node}"

                        if buf_key in forecast.point_forecast:
                            predicted_load = float(np.mean(forecast.get_mean(buf_key)[:8]))
                        else:
                            predicted_load = float(route.current_occupancy)

                        transit_penalty = route.transit_time_ns / 1_000_000_000.0
                        total_score = predicted_load + 0.1 * transit_penalty

                        if total_score < lowest_projected_load:
                            lowest_projected_load = total_score
                            best_route = route

                    unit_id = obs.unit_id if isinstance(obs, RoutingObservation) else None
                    actions.append(
                        RoutingAction(
                            target_id=req.target_id,
                            route_id=best_route.route_id,
                            unit_id=unit_id,
                        )
                    )

            # =================================================================
            # 3. MIKRO-EBENE: Puffer-Reordering (Reihenfolge) & Maintenance
            # =================================================================
            elif req.action_schema == "buffer_reorder" or isinstance(req.observation, BufferObservation):
                obs = req.observation
                occupants = list(obs.occupants) if isinstance(obs, BufferObservation) else []

                if occupants:
                    def compute_occupant_priority(u: BufferOccupantSummary) -> float:
                        due_t = u.due_date_ns if u.due_date_ns is not None else float("inf")
                        time_left_s = (due_t - current_time_ns) / 1e9

                        v_lower = (u.variant or "").lower()
                        if "heavy" in v_lower or "suv" in v_lower:
                            dur_est = 65.0
                        elif "express" in v_lower or "compact" in v_lower:
                            dur_est = 15.0
                        else:
                            dur_est = 35.0

                        # Advance short express jobs under high forecasted surge pressure
                        return time_left_s + 0.20 * surge_level * dur_est

                    sorted_occupants = sorted(occupants, key=compute_occupant_priority)
                    actions.append(
                        BufferReorderAction(
                            target_id=req.target_id,
                            new_order=[u.unit_id for u in sorted_occupants],
                        )
                    )

            elif req.action_schema in ("maintenance", "machine_mode") or isinstance(req.observation, MachineObservation):
                obs = req.observation
                m_id = obs.machine_id if isinstance(obs, MachineObservation) else req.target_id
                target_key = f"machine_health_{m_id}"
                current_health = obs.health if isinstance(obs, MachineObservation) else 1.0

                trigger = False
                if target_key in forecast.quantile_forecast:
                    # 10th percentile pessimistic degradation forecast
                    pessimistic_health = np.min(forecast.get_quantile(target_key, q=0.1))
                    if pessimistic_health < (1.0 - self.maintenance_risk_threshold) or current_health < 0.38:
                        trigger = True
                elif current_health < 0.40:
                    trigger = True

                if req.action_schema == "maintenance":
                    actions.append(
                        MaintenanceAction(
                            target_id=req.target_id,
                            trigger_maintenance=trigger,
                        )
                    )
                else:
                    mode = "eco" if current_health < 0.50 else ("boost" if is_surge_expected else "nominal")
                    actions.append(
                        MachineModeAction(
                            target_id=req.target_id,
                            mode=mode,
                        )
                    )

            if len(actions) > act_count_before:
                handled_targets.add(req.target_id)

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

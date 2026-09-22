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
    MachineObservation,
    MaintenanceAction,
    RoutingAction,
    RoutingObservation,
)
from industrialsim.forecasting.protocol import TimeSeriesForecaster

logger = logging.getLogger(__name__)


class PredictiveDecisionProvider(DecisionProvider):
    """
    Online closed-loop DecisionProvider utilizing time-series forecasting models.
    At decision points, it gathers historical telemetry, constructs upcoming
    production-plan signals, invokes the forecaster, and derives proactive actions.
    """

    def __init__(
        self,
        forecaster: TimeSeriesForecaster,
        provider_id: str = "predictive_forecaster",
        model_id: str = "timesfm-3",
        horizon: int = 32,
        maintenance_risk_threshold: float = 0.65,
        future_plan_entries: list[dict[str, Any]] | None = None,
    ) -> None:
        self.forecaster = forecaster
        self.provider_id = provider_id
        self.model_id = model_id
        self.horizon = horizon
        self.maintenance_risk_threshold = maintenance_risk_threshold
        self.future_plan_entries = future_plan_entries or []

        # Internal state buffer for recent observations
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
        """Feed telemetry snapshot from simulation into provider."""
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
        """Construct planned production release and load signals from the Production Plan."""
        if not self.future_plan_entries:
            # Default synthetic planned load signal if no explicit plan provided
            return {"planned_release_rate": np.ones(self.horizon, dtype=np.float64)}

        # Approximate time step between decisions (~10-30s in ns)
        step_dt_ns = 30_000_000_000
        time_grid = current_time_ns + np.arange(1, self.horizon + 1) * step_dt_ns

        planned_quantities = np.zeros(self.horizon, dtype=np.float64)
        for entry in self.future_plan_entries:
            rel_t = int(entry.get("release_time_ns", entry.get("release_time", 0)))
            qty = float(entry.get("quantity", 1))
            # Find nearest grid step
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
            elif isinstance(obs, RoutingObservation):
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

        # Run model forecast
        forecast = self.forecaster.forecast(
            past_targets=past_targets,
            past_covariates=past_covariates,
            future_covariates=future_covariates,
            horizon=self.horizon,
        )

        for req in batch.requests:
            # 1. Maintenance Requests
            if req.action_schema == "maintenance" and isinstance(req.observation, MachineObservation):
                obs = req.observation
                m_id = obs.machine_id
                target_key = f"machine_health_{m_id}"

                trigger = False
                if target_key in forecast.quantile_forecast:
                    # Check 10th percentile (worst-case health) over upcoming horizon
                    pessimistic_health = np.min(forecast.get_quantile(target_key, q=0.1))
                    # Or current health degraded and trend falling
                    if pessimistic_health < (1.0 - self.maintenance_risk_threshold) or obs.health < 0.35:
                        trigger = True
                elif obs.health < 0.40:
                    trigger = True

                actions.append(
                    MaintenanceAction(
                        target_id=req.target_id,
                        trigger_maintenance=trigger,
                    )
                )

            # 2. Routing Decisions
            elif req.action_schema == "routing" and isinstance(req.observation, RoutingObservation):
                obs = req.observation
                if obs.candidate_routes:
                    best_route = obs.candidate_routes[0]
                    lowest_congestion = float("inf")

                    for route in obs.candidate_routes:
                        target_node = route.target_node_id
                        buf_key = f"buffer_load_{target_node}"

                        if buf_key in forecast.point_forecast:
                            # Evaluate predicted buffer load
                            predicted_load = float(np.mean(forecast.get_mean(buf_key)[:8]))
                        else:
                            predicted_load = float(route.current_occupancy)

                        total_cost = predicted_load + (route.transit_time_ns / 1_000_000_000.0)
                        if total_cost < lowest_congestion:
                            lowest_congestion = total_cost
                            best_route = route

                    actions.append(
                        RoutingAction(
                            target_id=req.target_id,
                            route_id=best_route.route_id,
                            unit_id=obs.unit_id,
                        )
                    )

            # 3. Buffer Reordering Decisions
            elif req.action_schema == "buffer_reorder" and isinstance(req.observation, BufferObservation):
                obs = req.observation
                occupants = list(obs.occupants)
                if occupants:
                    # Dynamic priority balancing deadline urgency with forecasted congestion surge
                    predicted_wip = float(np.mean(forecast.get_mean("wip")[:8])) if "wip" in forecast.point_forecast else 1.0
                    recent_wip = self._history_wip[-1] if self._history_wip else 1.0
                    surge_level = max(0.0, predicted_wip - recent_wip)

                    def compute_occupant_urgency(u: BufferOccupantSummary) -> float:
                        due_t = u.due_date_ns if u.due_date_ns is not None else float("inf")
                        time_left_s = (due_t - current_time_ns) / 1e9

                        # Approximate duration estimate based on variant
                        v_lower = (u.variant or "").lower()
                        if "heavy" in v_lower or "suv" in v_lower:
                            dur_est = 90.0
                        elif "compact" in v_lower or "express" in v_lower:
                            dur_est = 15.0
                        else:
                            dur_est = 45.0

                        # When a surge is forecasted, clearing quick jobs prevents bottleneck gridlock
                        return time_left_s + 0.15 * surge_level * dur_est

                    sorted_occupants = sorted(occupants, key=compute_occupant_urgency)
                    actions.append(
                        BufferReorderAction(
                            target_id=req.target_id,
                            new_order=[u.unit_id for u in sorted_occupants],
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

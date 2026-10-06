"""Finite action catalogs and bounded, jointly validated Decision Batch search."""
from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
from typing import Any, Callable, Sequence
from pydantic import TypeAdapter

from industrialsim.decisions import (
    BufferObservation, BufferReorderAction, DecisionAction, DecisionBatch,
    DecisionBatchResponse, DecisionProvenance, DecisionRequest, DispatchAction,
    DispatchObservation, MachineModeAction, MachineObservation, MaintenanceAction,
    QualityControlAction, ReconfigurationAction, RoutingAction, RoutingObservation,
    StrategicObservation, WorkerReassignmentAction, validate_decision_batch_response,
)
from industrialsim.world_model.contracts import digest


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    action: DecisionAction


def model_action(action: DecisionAction, request: DecisionRequest | None, time_ns: int) -> dict[str, Any]:
    data = action.model_dump(mode="json")
    if isinstance(action, BufferReorderAction) and request is not None and isinstance(request.observation, BufferObservation):
        occupants = request.observation.occupants
        old = {unit.unit_id: i for i, unit in enumerate(occupants)}
        size = len(occupants)
        data["reorder_distance"] = (sum(abs(i - old[uid]) for i, uid in enumerate(action.new_order)) /
                                    max(1, size * size))
        first = next((u for u in occupants if action.new_order and u.unit_id == action.new_order[0]), None)
        data["head_due_delta_hours"] = ((first.due_date_ns - time_ns) / (3600 * 10**9)
                                          if first is not None and first.due_date_ns is not None else 0.0)
    return data


def public_batch(batch: DecisionBatch) -> DecisionBatch:
    """Compatibility shim; the model never receives exact health or hidden metrics."""
    requests = []
    for request in batch.requests:
        obs = request.observation
        if isinstance(obs, MachineObservation):
            obs = obs.model_copy(update={"health": 0.5, "physical_state": {},
                                          "maintenance_policy_summary": {}, "aggregate_metrics": {}})
        elif hasattr(obs, "aggregate_metrics"):
            obs = obs.model_copy(update={"aggregate_metrics": {}})
        requests.append(request.model_copy(update={"observation": obs}))
    return batch.model_copy(update={"requests": requests})


class CandidateCatalog:
    schema_version = "industrial-candidates/1.0"

    def __init__(self, station_ids: Sequence[str] = (),
                 reconfigurations: Sequence[dict[str, Any]] = ()) -> None:
        self.station_ids = tuple(sorted(station_ids))
        self.reconfigurations = tuple(reconfigurations)

    def candidates(self, request: DecisionRequest, busy: bool = False) -> tuple[Candidate, ...]:
        if request.candidate_catalog_version is not None:
            if request.candidate_catalog_version != self.schema_version:
                raise ValueError("Incompatible candidate catalog")
            adapter: TypeAdapter[Any] = TypeAdapter(DecisionAction)
            return tuple(Candidate(digest(data), adapter.validate_python(data)) for data in request.candidate_catalog)
        obs, target = request.observation, request.target_id
        actions: list[DecisionAction] = []
        if isinstance(obs, BufferObservation):
            occupants = list(obs.occupants)
            orderings = [occupants, sorted(occupants, key=lambda u: (u.due_date_ns or 2**63, u.unit_id)),
                         list(reversed(occupants))]
            actions = [BufferReorderAction(target_id=target, new_order=[u.unit_id for u in order])
                       for order in orderings]
        elif isinstance(obs, RoutingObservation):
            actions = [RoutingAction(target_id=target, unit_id=obs.unit_id, route_id=r.route_id)
                       for r in obs.candidate_routes if r.is_admissible]
        elif isinstance(obs, DispatchObservation):
            actions = [DispatchAction(target_id=target, route_id=r.route_id, vehicle_id=v.vehicle_id)
                       for r in obs.candidate_routes if r.is_admissible for v in obs.available_vehicles]
            if not obs.available_vehicles:
                actions = [DispatchAction(target_id=target, route_id=r.route_id)
                           for r in obs.candidate_routes if r.is_admissible]
        elif isinstance(obs, MachineObservation):
            actions = [MaintenanceAction(target_id=target, trigger_maintenance=False)]
            if not busy and not obs.is_failed and not obs.is_in_maintenance:
                if request.action_schema != "maintenance":
                    actions += [MachineModeAction(target_id=target, mode=mode)
                                for mode in sorted(set(obs.available_modes + [obs.operating_mode]))
                                if mode != "maintenance"]
                if request.action_schema != "machine_mode":
                    actions.append(MaintenanceAction(target_id=target))
        elif isinstance(obs, StrategicObservation) and request.is_safe_point and obs.is_safe_point:
            allowed = obs.allowed_actions
            if "reconfiguration" in allowed:
                actions += [ReconfigurationAction(target_id=target, configuration=dict(c),
                            duration_ns=0 if c == obs.current_configuration else 30_000_000_000,
                            cost=0.0 if c == obs.current_configuration else .1)
                            for c in (obs.current_configuration, *self.reconfigurations)]
            if "worker_reassignment" in allowed:
                actions += [WorkerReassignmentAction(target_id=target, assigned_station_id=sid,
                            cost=0.0 if sid == obs.current_configuration.get("assigned_station_id") else .02)
                            for sid in (None, *obs.current_configuration.get("compatible_station_ids", self.station_ids))]
            if "quality_control" in allowed:
                bounds = obs.quality_control_bounds
                controls: list[list[float]] = []
                for name in ("inspection_intensity", "sampling_rate", "release_threshold"):
                    low = getattr(bounds, "min_" + name, 0.0)
                    high = getattr(bounds, "max_" + name, 1.0)
                    current = float(obs.current_configuration.get(name, (low + high) / 2))
                    controls.append(sorted({low, min(high, max(low, current)), high}))
                actions += [QualityControlAction(target_id=target, inspection_intensity=a,
                                                 sampling_rate=b, release_threshold=c,
                            cost=0.0 if (a,b,c) == tuple(float(obs.current_configuration.get(key, .5))
                                for key in ("inspection_intensity", "sampling_rate", "release_threshold")) else .01)
                            for a, b, c in itertools.product(*controls)]
        unique = {digest(action.model_dump(mode="json")): action for action in actions}
        return tuple(Candidate(key, unique[key]) for key in sorted(unique))


def response_for(batch: DecisionBatch, actions: Sequence[DecisionAction], provider_id: str,
                 model_id: str | None = None) -> DecisionBatchResponse:
    return DecisionBatchResponse(batch_id=batch.batch_id, actions=list(actions),
        provenance=DecisionProvenance(episode_id=batch.episode_id, branch_id=batch.branch_id,
                                     batch_id=batch.batch_id, provider_id=provider_id, model_id=model_id))


def catalog_valid(batch: DecisionBatch, actions: Sequence[DecisionAction],
                  catalog: dict[str, tuple[Candidate, ...]]) -> bool:
    response = response_for(batch, actions, "catalog-validation")
    valid, _ = validate_decision_batch_response(batch, response)
    if not valid:
        return False
    route_targets = {route.route_id: route.target_node_id for r in batch.requests
                     if isinstance(r.observation, (RoutingObservation, DispatchObservation))
                     for route in r.observation.candidate_routes}
    reconfiguring = {a.target_id for a in actions if isinstance(a, ReconfigurationAction) and a.duration_ns > 0}
    if any(isinstance(a, (RoutingAction, DispatchAction)) and route_targets.get(a.route_id) in reconfiguring
           for a in actions):
        return False
    dispatch_units = {r.target_id: r.observation.unit_id for r in batch.requests
                      if isinstance(r.observation, DispatchObservation)}
    route_choices = {a.unit_id or a.target_id: a.route_id for a in actions if isinstance(a, RoutingAction)}
    if any(isinstance(a, DispatchAction) and dispatch_units.get(a.target_id) in route_choices
           and route_choices[dispatch_units[a.target_id]] != a.route_id for a in actions):
        return False
    available = {r.target_id: {c.candidate_id for c in catalog[r.request_id]} for r in batch.requests}
    return all(digest(a.model_dump(mode="json")) in available.get(a.target_id, set()) for a in actions)


class BoundedBatchPlanner:
    def __init__(self, beam_width: int = 32) -> None:
        if beam_width < 1:
            raise ValueError("Beam width must be positive")
        self.beam_width = beam_width

    def choose(self, batch: DecisionBatch, catalog: dict[str, tuple[Candidate, ...]],
               score: Callable[[Sequence[DecisionAction]], float],
               score_many: Callable[[Sequence[Sequence[DecisionAction]]], Sequence[float]] | None = None) -> list[DecisionAction]:
        requests = sorted(batch.requests, key=lambda r: (r.target_id, r.request_id))
        if len({r.target_id for r in requests}) != len(requests):
            raise ValueError("Duplicate targets in Decision Batch")
        # Complete partial beams with deterministic valid tails before scoring, so
        # the model always evaluates a complete batch, never missing actions.
        beams: list[tuple[Candidate, ...]] = [()]
        for index, request in enumerate(requests):
            expanded: list[tuple[float, tuple[str, ...], tuple[Candidate, ...]]] = []
            pending = []
            for prefix in beams:
                for candidate in catalog[request.request_id]:
                    new_prefix = (*prefix, candidate)
                    tails = self._complete(requests[index + 1:], catalog, new_prefix, requests)
                    if tails is None:
                        continue
                    full = [c.action for c in tails]
                    if not catalog_valid(batch, full, catalog):
                        continue
                    pending.append((full, tuple(c.candidate_id for c in tails), new_prefix))
            costs = (score_many([item[0] for item in pending]) if score_many is not None
                     else [score(item[0]) for item in pending])
            if len(costs) != len(pending):
                raise ValueError("Batched scorer returned the wrong number of costs")
            for (full, identifiers, new_prefix), value in zip(pending, costs):
                cost = float(value)
                if not math.isfinite(cost):
                    continue
                expanded.append((cost, identifiers, new_prefix))
            expanded.sort(key=lambda item: (item[0], item[1]))
            beams = [item[2] for item in expanded[:self.beam_width]]
            if not beams:
                raise ValueError("No jointly valid finite-scored batch")
        return [c.action for c in beams[0]]

    def _complete(self, requests: Sequence[DecisionRequest], catalog: dict[str, tuple[Candidate, ...]],
                  prefix: tuple[Candidate, ...], all_requests: Sequence[DecisionRequest] = ()) -> tuple[Candidate, ...] | None:
        result = list(prefix)
        route_targets = {route.route_id: route.target_node_id for r in all_requests
                         if isinstance(r.observation, (RoutingObservation, DispatchObservation))
                         for route in r.observation.candidate_routes}
        claimed = {c.action.vehicle_id for c in result if isinstance(c.action, DispatchAction)
                   and c.action.vehicle_id is not None}
        for request in requests:
            reconfiguring = {c.action.target_id for c in result
                             if isinstance(c.action, ReconfigurationAction) and c.action.duration_ns > 0}
            routed_targets = {route_targets.get(c.action.route_id) for c in result
                              if isinstance(c.action, (RoutingAction, DispatchAction))}
            chosen_routes = {c.action.unit_id or c.action.target_id: c.action.route_id
                             for c in result if isinstance(c.action, RoutingAction)}
            options = sorted(catalog[request.request_id], key=lambda c: (getattr(c.action, "cost", 0.0), c.candidate_id))
            chosen = next((c for c in options
                           if not isinstance(c.action, DispatchAction) or c.action.vehicle_id is None
                           or c.action.vehicle_id not in claimed
                           if not isinstance(c.action, DispatchAction) or not isinstance(request.observation, DispatchObservation)
                           or request.observation.unit_id not in chosen_routes
                           or c.action.route_id == chosen_routes[request.observation.unit_id]
                           if not isinstance(c.action, (RoutingAction, DispatchAction))
                           or route_targets.get(c.action.route_id) not in reconfiguring
                           if not isinstance(c.action, ReconfigurationAction) or c.action.duration_ns == 0
                           or c.action.target_id not in routed_targets), None)
            if chosen is None:
                return None
            result.append(chosen)
            if isinstance(chosen.action, DispatchAction) and chosen.action.vehicle_id is not None:
                claimed.add(chosen.action.vehicle_id)
        return tuple(result)

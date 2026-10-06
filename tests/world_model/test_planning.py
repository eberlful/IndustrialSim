from __future__ import annotations

from dataclasses import asdict
import pytest

from industrialsim.decisions import (BufferObservation, BufferOccupantSummary, DecisionBatch,
    DecisionRequest, DispatchObservation, MachineObservation, QualityControlBounds,
    RouteSummaryObservation, RoutingObservation, StrategicObservation, VehicleSummaryObservation)
from industrialsim.world_model.contracts import CHANNELS, PlantGraph, RolloutResult, StudyObservation
from industrialsim.world_model.planning import CandidateCatalog, BoundedBatchPlanner, catalog_valid, public_batch
from industrialsim.world_model.provider import WorldModelDecisionProvider
from industrialsim.config import RewardPolicyConfig


def request(target: str, observation: object) -> DecisionRequest:
    return DecisionRequest(request_id="req-" + target, time_ns=0, target_id=target,
                           observation=observation, is_safe_point=True)


def test_catalog_contains_all_eight_action_types_and_is_stable() -> None:
    catalog = CandidateCatalog(["st"], [{"cycle_time_multiplier": .8}])
    route = RouteSummaryObservation(route_id="r", source_node_id="b", target_node_id="st", transit_time_ns=1)
    requests = [request("b", BufferObservation(buffer_id="b", capacity=2, occupancy=1,
                occupants=[BufferOccupantSummary(unit_id="u", variant="sedan")])),
        request("u", RoutingObservation(unit_id="u", variant="sedan", current_node_id="b", candidate_routes=[route])),
        request("to", DispatchObservation(order_id="to", unit_id="u", variant="sedan", source_node_id="b",
                target_node_id="st", created_time_ns=0, candidate_routes=[route],
                available_vehicles=[VehicleSummaryObservation(vehicle_id="v", location="b")])),
        request("m", MachineObservation(machine_id="m", health=.17, available_modes=["nominal", "eco"])),
        request("st", StrategicObservation(target_id="st", allowed_actions=["reconfiguration", "quality_control"],
                                             quality_control_bounds=QualityControlBounds())),
        request("w", StrategicObservation(target_id="w", allowed_actions=["worker_reassignment"]))]
    kinds = {c.action.action_type for r in requests for c in catalog.candidates(r)}
    assert kinds == {"buffer_reorder", "routing", "dispatch", "machine_mode", "maintenance",
                     "reconfiguration", "worker_reassignment", "quality_control"}
    assert catalog.candidates(requests[0]) == catalog.candidates(requests[0])
    busy = catalog.candidates(requests[3], busy=True)
    assert len(busy) == 1 and busy[0].action.trigger_maintenance is False


def test_joint_search_prevents_duplicate_vehicle_claims_and_scores_complete_batches() -> None:
    route = RouteSummaryObservation(route_id="r", source_node_id="b", target_node_id="st", transit_time_ns=1)
    reqs = [request(target, DispatchObservation(order_id=target, unit_id=target + "-u", variant="sedan",
        source_node_id="b", target_node_id="st", created_time_ns=0, candidate_routes=[route],
        available_vehicles=[VehicleSummaryObservation(vehicle_id=v, location="b") for v in ("v1", "v2")]))
        for target in ("to1", "to2")]
    batch = DecisionBatch(batch_id="batch", episode_id="ep", time_ns=0, requests=reqs)
    catalog = {r.request_id: CandidateCatalog().candidates(r) for r in reqs}
    scored = []
    def score(actions):
        assert len(actions) == 2
        scored.append(actions)
        return 0.
    actions = BoundedBatchPlanner().choose(batch, catalog, score)
    assert catalog_valid(batch, actions, catalog)
    assert len({a.vehicle_id for a in actions}) == 2
    assert scored


def test_public_batch_does_not_expose_health_to_model_or_fallback() -> None:
    batch = DecisionBatch(batch_id="b", episode_id="e", time_ns=0,
        requests=[request("m", MachineObservation(machine_id="m", health=.13,
            physical_state={"health": .13}, aggregate_metrics={"latent_health": .13}))])
    obs = public_batch(batch).requests[0].observation
    assert obs.health == .5 and not obs.physical_state and not obs.aggregate_metrics


def test_joint_search_rejects_transport_into_reconfiguring_station() -> None:
    route = RouteSummaryObservation(route_id="r", source_node_id="b", target_node_id="st", transit_time_ns=1)
    reqs = [request("u", RoutingObservation(unit_id="u", variant="sedan", current_node_id="b",
                                           candidate_routes=[route])),
            request("st", StrategicObservation(target_id="st", allowed_actions=["reconfiguration"]))]
    batch = DecisionBatch(batch_id="batch", episode_id="ep", time_ns=0, requests=reqs)
    factory = CandidateCatalog(["st"], [{"cycle_time_multiplier": .8}])
    catalog = {r.request_id: factory.candidates(r) for r in reqs}
    # Even a score that strongly prefers reconfiguration cannot bypass validity.
    actions = BoundedBatchPlanner().choose(batch, catalog,
        lambda actions: -sum(getattr(a, "duration_ns", 0) for a in actions))
    assert catalog_valid(batch, actions, catalog)
    assert next(a for a in actions if a.action_type == "reconfiguration").duration_ns == 0


def test_model_exception_applies_valid_engine_fallback() -> None:
    from industrialsim.world_model.study import StudyEngine, StudySettings, install_sampling, research_configuration
    from industrialsim.world_model.observation import StudyObservationAdapter
    class FailingProvider:
        def decide(self, batch):
            raise RuntimeError("model unavailable")
    settings = StudySettings(duration_ns=1500 * 10**9)
    engine = StudyEngine.create(research_configuration(settings, 42, "test"))
    engine.decision_provider = FailingProvider()
    install_sampling(engine, StudyObservationAdapter(), "episode", settings)
    engine.run(pause_at_ns=30 * 10**9)
    assert any(record.event_type == "fallback" for record in engine.audit_logger.records_since(0))
    assert any(action.status == "applied" for action in engine.action_evidence)


def test_model_failures_reach_existing_fallback_and_are_counted() -> None:
    class FailingModel:
        def rollout(self, *args, **kwargs):
            raise RuntimeError("inference failed")
    provider = WorldModelDecisionProvider(FailingModel(), CandidateCatalog(),
        RewardPolicyConfig.model_validate({"components": [{"name": "good_output"}]}), [], "test")
    graph = PlantGraph(("m",), ("machine",), (), (1.,), ("generic",))
    provider.update_observation(StudyObservation("ep", "main", 0,
        (tuple([0.] * len(CHANNELS)),), (tuple([True] * len(CHANNELS)),)), graph)
    batch = DecisionBatch(batch_id="b", episode_id="ep", time_ns=0,
        requests=[request("m", MachineObservation(machine_id="m", health=.8))])
    with pytest.raises(RuntimeError, match="inference failed"):
        provider.decide(batch)
    assert provider.fallback_count == 1

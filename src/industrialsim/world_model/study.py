"""Reproducible synthetic study episodes, action evidence, and grouped splits."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
import copy
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from typing import Any, Sequence

import numpy as np
from ruamel.yaml import YAML

from industrialsim.application import EpisodeEngine
from industrialsim.config import SimulationConfig
from industrialsim.decisions import (DecisionBatch, DecisionBatchResponse, DecisionDiagnosticRecord,
    DecisionProvider, DecisionRequest,
    BufferObservation, DispatchObservation, RoutingObservation,
    MachineObservation, MachineModeAction, QualityControlBounds, StrategicObservation)
from industrialsim.checkpoint import save_checkpoint
from industrialsim.kernel import EventPriority
from industrialsim.world_model.contracts import (ACTION_TYPES, CHANNELS, SCHEMA_VERSION, STEP_NS,
                                               TimedAction, digest, portable)
from industrialsim.world_model.observation import StudyObservationAdapter, graph_from_engine
from industrialsim.world_model.planning import (BoundedBatchPlanner, CandidateCatalog, catalog_valid,
                                               public_batch, response_for, model_action)

COUNTS = {"train": 160, "validation": 40, "test": 40, "unknown_parameters": 40,
          "unknown_topology": 40, "unknown_combinations": 40}
HELD_OUT = ("boost", "high_inspection")


@dataclass(frozen=True)
class StudySettings:
    reference_config: str = "examples/reference_automotive_plant.yaml"
    duration_ns: int = 7_200_000_000_000
    interval_ns: int = STEP_NS
    context: int = 32
    horizon: int = 10
    seed: int = 5000
    noise_scale: float = 0.02
    missing_probability: float = 0.02
    counts: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.interval_ns != STEP_NS or self.context != 32 or self.horizon != 10:
            raise ValueError("EXP-0005 fixes the 30-second grid, 32-step context and 10-step horizon")
        if self.duration_ns < (self.context + self.horizon) * self.interval_ns:
            raise ValueError("Episode shorter than one training window")
        if self.counts is not None and (set(self.counts) != set(COUNTS) or any(v < 1 for v in self.counts.values())):
            raise ValueError("Provide positive counts for every predefined split")


def load_settings(path: str | Path | None) -> StudySettings:
    return StudySettings(**json.loads(Path(path).read_text())) if path else StudySettings()


def research_configuration(settings: StudySettings, seed: int, stratum: str,
                           long_term: bool = False) -> SimulationConfig:
    raw = YAML(typ="safe").load(Path(settings.reference_config).read_text())
    raw["seed"] = seed
    duration = 5 * 86400 * 10**9 if long_term else settings.duration_ns
    raw["episode"] = {"start_time": 0, "warm_up_time": 0,
                      "end_condition": {"type": "max_time", "max_time": duration}}
    raw["telemetry"] = {"enabled": False}
    raw["decision_triggers"] = []
    raw["production_units"] = []
    release_step = 120 * 10**9
    raw["production_plan"] = [{"id": f"release-{i}", "variant": "sedan" if i % 2 else "suv",
                              "quantity": 1, "source_id": "src-bodies", "release_time": i * release_step,
                              "due_date": i * release_step + 3600 * 10**9}
                             for i in range(max(1, duration // release_step))]
    raw["reward_policy"] = {"components": [
        {"name": "good_output", "weight": 1.0},
        {"name": "scrap", "weight": 2.0, "direction": "minimize"},
        {"name": "wip", "weight": 0.05, "direction": "minimize"},
        {"name": "lateness_ns", "weight": 0.1, "scale": 60 * 10**9, "direction": "minimize"},
        {"name": "total_strategic_cost", "weight": 1.0, "direction": "minimize"}]}
    effects = {
        "op-body-weld": {"weld_stress": {"bias": 0.1, "health_weight": 0.6,
                                           "mode_weights": {"boost": 0.2, "eco": -0.05}}},
        "op-paint-pretreat": {"surface_residue": {"bias": 0.05, "inputs": {"weld_stress": 0.4},
                                                  "health_weight": 0.4}},
        "op-paint-spray": {"coating_variation": {"bias": 0.04, "inputs": {"surface_residue": 0.7},
                                                 "health_weight": 0.5, "mode_weights": {"boost": 0.15}}},
        "op-paint-dry": {"cure_deficit": {"bias": 0.03, "inputs": {"coating_variation": 0.6},
                                         "mode_weights": {"boost": 0.15, "eco": -0.02}}},
        "op-rework": {"coating_variation": {"bias": 0.02}, "cure_deficit": {"bias": 0.02}},
    }
    for node in raw["material_flow"]["nodes"]:
        for op in node.get("operations", []):
            if op["id"] in effects:
                op["process_effects"] = effects[op["id"]]
            if op["id"] in ("op-assembly-trim", "op-assembly-chassis"):
                op["process_defect_weights"] = {"weld_stress": 0.1, "cure_deficit": 0.2}
            # Deterministic parameter families within each split.
            if stratum == "unknown_parameters":
                for effect in op.get("process_effects", {}).values():
                    effect["health_weight"] = effect.get("health_weight", 0) * 1.8
    for machine in raw.get("machines", []):
        machine["initial_health"] = 0.7 + 0.25 * ((seed + len(machine["id"])) % 11) / 10
        machine["modes"] = {
            "nominal": {"cycle_time_multiplier": 1.0, "degradation_multiplier": 1.0},
            "eco": {"cycle_time_multiplier": 1.2, "degradation_multiplier": 0.6},
            "boost": {"cycle_time_multiplier": 0.8, "degradation_multiplier": 1.6}}
        machine["maintenance"] = {"trigger": "manual", "duration": "60s", "restored_health": 1.0}
    if stratum == "unknown_topology":
        nodes = raw["material_flow"]["nodes"]
        clone = copy.deepcopy(next(n for n in nodes if n["id"] == "st-body-2"))
        clone["id"] = "st-body-3"
        clone["operations"][0]["required_machines"] = ["m-body-welder-3"]
        nodes.append(clone)
        machine = copy.deepcopy(next(m for m in raw["machines"] if m["id"] == "m-body-welder-2"))
        machine["id"] = "m-body-welder-3"
        raw["machines"].append(machine)
        routes = raw["material_flow"]["routes"]
        additions = []
        for route in routes:
            if "st-body-2" in (route["source_node_id"], route["target_node_id"]):
                extra = copy.deepcopy(route)
                extra["id"] += "-parallel-3"
                for key in ("source_node_id", "target_node_id"):
                    if extra[key] == "st-body-2":
                        extra[key] = "st-body-3"
                additions.append(extra)
        routes.extend(additions)
        for plan in raw["process_plans"]:
            plan["steps"][0]["compatible_stations"].append("st-body-3")
    return SimulationConfig.model_validate(raw)


class StudyEngine(EpisodeEngine):
    """Study instrumentation is opt-in; production random streams are untouched."""
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.action_evidence: list[TimedAction] = []
        self.study_observations: list[Any] = []
        self.study_labels: list[dict[str, Any]] = []
        self.deferred_machine_requests: set[str] = set()
        self.routing_evidence_by_order: dict[str, dict[str, Any]] = {}
        self.study_fallback_policy = StudyFallbackPolicy(self)

    def _create_transport_order(self, unit_id: str, source_node_id: str, time_ns: int) -> Any:
        order = super()._create_transport_order(unit_id, source_node_id, time_ns)
        obs = self._build_routing_observation(source_node_id, time_ns, unit_id)
        if any(r.is_admissible for r in obs.candidate_routes) and not any(
                r.target_id == unit_id for r in self.decision_coordinator.pending_requests):
            self.decision_coordinator.add_request(DecisionRequest(
                request_id=f"study-route-{order.id}-{time_ns}", request_type="study",
                target_id=unit_id, time_ns=time_ns, observation=obs, action_schema="routing"))
        return order

    def _try_dispatch_pending_orders(self, kernel: Any) -> None:
        # Keep routing requests at a consistent pause point before dispatch. Only
        # the study subclass changes this behavior; the production kernel stays intact.
        pending_targets = {r.target_id for r in self.decision_coordinator.pending_requests}
        for oid in list(self.pending_transport_orders):
            order = self.transport_orders[oid]
            if order.assigned_route_id is None and order.unit_id not in pending_targets:
                obs = self._build_routing_observation(order.source_node_id, kernel.current_time_ns, order.unit_id)
                if any(r.is_admissible for r in obs.candidate_routes):
                    self.decision_coordinator.add_request(DecisionRequest(
                        request_id=f"study-route-{oid}-{kernel.current_time_ns}", request_type="study",
                        target_id=order.unit_id, time_ns=kernel.current_time_ns,
                        observation=obs, action_schema="routing"))
                    pending_targets.add(order.unit_id)
        pending_units = {r.target_id for r in self.decision_coordinator.pending_requests
                         if r.action_schema == "routing"}
        if pending_units:
            original = self.domain.pending_transport_orders
            deferred = [oid for oid in original if self.transport_orders[oid].unit_id in pending_units]
            self.domain.pending_transport_orders = [oid for oid in original if oid not in deferred]
            super()._try_dispatch_pending_orders(kernel)
            self.domain.pending_transport_orders.extend(deferred)
            self._pending_orders_sorted = False
        else:
            super()._try_dispatch_pending_orders(kernel)

    def _build_observation_for_request(self, req_or_target: Any, time_ns: int) -> Any:
        if getattr(req_or_target, "request_type", "") != "study":
            return super()._build_observation_for_request(req_or_target, time_ns)
        # Pending requests are a pause barrier, not a physical capacity claim.
        # Refresh all observations against the same physical state of this batch.
        pending = self.decision_coordinator.pending_requests
        self.decision_coordinator.pending_requests = []
        try:
            obs = req_or_target.observation
            if isinstance(obs, BufferObservation):
                return self._build_buffer_observation(obs.buffer_id, time_ns)
            if isinstance(obs, MachineObservation):
                return self._build_machine_observation(obs.machine_id, time_ns).model_copy(
                    update={"available_modes": sorted(self.machines[obs.machine_id].modes)})
            if isinstance(obs, RoutingObservation):
                return self._build_routing_observation(obs.current_node_id, time_ns, obs.unit_id)
            if isinstance(obs, DispatchObservation):
                return self._build_dispatch_observation(time_ns, obs.order_id)
            return obs
        finally:
            self.decision_coordinator.pending_requests = pending

    def _process_decision_batch(self) -> None:
        start = self.audit_logger.record_count
        catalog = CandidateCatalog(sorted(self.stations),
                                   ({"cycle_time_multiplier": .85}, {"cycle_time_multiplier": 1.15}))
        requests = []
        for request in self.decision_coordinator.pending_requests:
            request = request.model_copy(update={"observation": self._build_observation_for_request(
                request, self.kernel.current_time_ns)})
            busy = request.target_id in self.machines and bool(self.machines[request.target_id].active_allocations)
            options = catalog.candidates(request, busy)
            if not options:
                self.audit_logger.record(event_type="decision_deferred", simulated_time_ns=self.kernel.current_time_ns,
                    episode_id=self.decision_coordinator.episode_id,
                    branch_id=self.decision_coordinator.branch_id, entity_ids=[request.target_id],
                    details={"reason": "No currently admissible candidate", "request_id": request.request_id})
                continue
            requests.append(request.model_copy(update={"candidate_catalog_version": catalog.schema_version,
                "candidate_catalog": [c.action.model_dump(mode="json") for c in options]}))
        self.decision_coordinator.pending_requests = requests
        super()._process_decision_batch()
        records = self.audit_logger.records_since(start)
        failed = {r.batch_id for r in records if r.event_type == "fallback"}
        for record in records:
            action = record.details.get("action")
            provider = (record.provenance or {}).get("provider_id", "") or ""
            if (record.event_type == "decision_action" and record.batch_id in failed
                    and action is not None and not provider.startswith("fallback")):
                self.action_evidence.append(TimedAction(record.simulated_time_ns, action, "rejected",
                                                       "Decision Batch validation failed"))

    def _validate_decision_response(self, batch: DecisionBatch, response: DecisionBatchResponse
                                    ) -> tuple[bool, list[DecisionDiagnosticRecord]]:
        valid, diagnostics = super()._validate_decision_response(batch, response)
        catalog = {r.request_id: CandidateCatalog().candidates(r) for r in batch.requests}
        if valid and not catalog_valid(batch, response.actions, catalog):
            diagnostics.append(DecisionDiagnosticRecord(code="INVALID_STUDY_BATCH", batch_id=batch.batch_id,
                message="Actions violate the shared finite catalog or joint study constraints"))
            return False, diagnostics
        return valid, diagnostics

    def _apply_actions_list(self, batch: Any, actions: Sequence[Any]) -> None:
        payloads = {a.target_id: model_action(a, next((r for r in batch.requests if r.target_id == a.target_id), None),
                                            batch.time_ns) for a in actions}
        for action in actions:
            self.action_evidence.append(TimedAction(batch.time_ns, payloads[action.target_id], "proposed"))
            if action.action_type == "routing":
                oid = self._active_transport_orders_by_unit.get(action.unit_id or action.target_id)
                if oid:
                    self.routing_evidence_by_order[oid] = action.model_dump(mode="json")
        # Record actual effects, rather than treating acceptance as actuation.
        before = {a.target_id: self._action_state(a) for a in actions}
        super()._apply_actions_list(batch, actions)
        for action in actions:
            data = payloads[action.target_id]
            if action.action_type in ("routing", "dispatch"):
                continue  # Effect is recorded at actual transport dispatch.
            changed = before[action.target_id] != self._action_state(action)
            self.action_evidence.append(TimedAction(batch.time_ns, data, "applied" if changed else "no_effect"))
            if action.target_id in self.machines and self.machines[action.target_id].active_allocations:
                self.deferred_machine_requests.add(action.target_id)

    def _action_state(self, action: Any) -> Any:
        target = action.target_id
        if target in self.machines:
            m = self.machines[target]
            return (m.operating_mode, m.is_in_maintenance, m.health)
        if target in self.buffers:
            return tuple(self.buffers[target].occupants)
        if target in self.workers:
            w = self.workers[target]
            return (w.assigned_station_id, tuple(w.qualifications))
        if target in self.stations:
            s = self.stations[target]
            return digest({"configuration": s.configuration, "inspection":
                           {key: op.inspection for key, op in s.operations.items()}})
        return None

    def _execute_dispatch_decision(self, kernel: Any, decision: Any) -> None:
        super()._execute_dispatch_decision(kernel, decision)
        routing = self.routing_evidence_by_order.pop(decision.order.id, None)
        if routing is not None:
            self.action_evidence.append(TimedAction(kernel.current_time_ns, routing,
                "applied" if routing["route_id"] == decision.route.id else "no_effect"))
        self.action_evidence.append(TimedAction(kernel.current_time_ns,
            {"action_type": "dispatch", "target_id": decision.order.source_node_id,
             "route_id": decision.route.id, "vehicle_id": decision.vehicle.id if decision.vehicle else None}))

    def _release_resources(self, station_id: str, time_ns: int, completed: bool = False) -> Any:
        result = super()._release_resources(station_id, time_ns, completed)
        for mid in sorted(self.deferred_machine_requests):
            if not self.machines[mid].active_allocations:
                self.kernel.schedule(time_ns, 90, "STUDY_IDLE", payload={"machine_id": mid})
        return result


class ExplorationProvider(DecisionProvider):
    def __init__(self, engine: StudyEngine, stratum: str, policy: str = "random") -> None:
        self.engine, self.stratum, self.policy = engine, stratum, policy
        self.catalog = CandidateCatalog(sorted(engine.stations),
                                        ({"cycle_time_multiplier": 0.85}, {"cycle_time_multiplier": 1.15}))
        self.planner = BoundedBatchPlanner(beam_width=1)

    def decide(self, batch: DecisionBatch) -> Any:
        batch = public_batch(batch)
        catalog = {r.request_id: self.catalog.candidates(r, bool(
            self.engine.machines[r.target_id].active_allocations) if r.target_id in self.engine.machines else False)
                   for r in batch.requests}
        # Hold out concurrent boost + high inspection for an entire Episode,
        # including persisted operating modes, rather than merely one batch.
        permit_boost = self.stratum == "unknown_combinations" or self.engine.cfg.seed % 2 == 0
        permit_high = self.stratum == "unknown_combinations" or not permit_boost
        for key, options in catalog.items():
            catalog[key] = tuple(c for c in options
                if (permit_boost or getattr(c.action, "mode", "") != "boost") and
                (permit_high or (getattr(c.action, "inspection_intensity", None) or 0) < 0.99))
        action_costs = {id(c.action): self.engine.random_stream.draw_float(
            "study_exploration", c.action.target_id, c.candidate_id, batch.time_ns)
            for options in catalog.values() for c in options}
        def score(actions: Sequence[Any]) -> float:
            if self.policy == "heuristic":
                return sum(float(getattr(a, "cost", 0.0)) +
                           (0 if getattr(a, "mode", "nominal") == "nominal" else 1) +
                           (1 if getattr(a, "trigger_maintenance", False) else 0) for a in actions)
            return sum(action_costs[id(a)] for a in actions)
        actions = self.planner.choose(batch, catalog, score)
        return response_for(batch, actions, "study-" + self.policy)


class StudyFallbackPolicy:
    """Deterministic baseline fallback over public observations and valid catalogs."""
    def __init__(self, engine: StudyEngine) -> None:
        self.engine = engine

    def generate_fallback_actions(self, batch: DecisionBatch) -> list[Any]:
        # Reuse the same finite search and public observation path as the study
        # heuristic; unlike the legacy fallback it cannot consult exact health.
        return list(ExplorationProvider(self.engine, "test", "heuristic").decide(public_batch(batch)).actions)


def install_sampling(engine: StudyEngine, adapter: StudyObservationAdapter, episode_id: str,
                     settings: StudySettings, branch_id: str = "main", decisions: bool = True) -> None:
    graph = graph_from_engine(engine)
    def request(target: str, obs: Any, schema: str, time: int) -> None:
        if any(r.target_id == target for r in engine.decision_coordinator.pending_requests):
            return
        engine.decision_coordinator.add_request(DecisionRequest(
            request_id=f"study-{target}-{time}", request_type="study", target_id=target,
            time_ns=time, is_safe_point=True, observation=obs, action_schema=schema))
    def idle(kernel: Any, event: Any) -> None:
        mid = event.payload["machine_id"]
        engine.deferred_machine_requests.discard(mid)
        obs = engine._build_machine_observation(mid, kernel.current_time_ns)
        obs = obs.model_copy(update={"available_modes": sorted(engine.machines[mid].modes)})
        request(mid, obs, "machine", kernel.current_time_ns)
    def sample(kernel: Any, event: Any) -> None:
        time = kernel.current_time_ns
        observation = adapter.observe(engine, graph, episode_id, branch_id)
        engine.study_observations.append(observation)
        engine.study_labels.append(adapter.labels(engine))
        update_observation = getattr(engine.decision_provider, "update_observation", None)
        if update_observation is not None:
            update_observation(observation, graph)
        if decisions:
            for bid in sorted(engine.buffers):
                request(bid, engine._build_buffer_observation(bid, time), "buffer_reorder", time)
            for mid in sorted(engine.machines):
                obs = engine._build_machine_observation(mid, time)
                obs = obs.model_copy(update={"available_modes": sorted(engine.machines[mid].modes)})
                request(mid, obs, "machine", time)
            for sid, station in sorted(engine.stations.items()):
                if station.is_busy or station.is_blocked or engine.in_flight_to.get(sid, 0) > 0:
                    continue
                inspecting = any(op.inspection for op in station.operations.values())
                config = dict(station.configuration)
                if inspecting:
                    inspection = next(op.inspection for op in station.operations.values() if op.inspection)
                    config.update(inspection_intensity=inspection.get("sensitivity", 0.5),
                                  sampling_rate=inspection.get("sampling_rate", 1.0),
                                  release_threshold=inspection.get("release_threshold", 0.5))
                request(sid, StrategicObservation(target_id=sid, current_configuration=config,
                    allowed_actions=["quality_control"] if inspecting else ["reconfiguration"],
                    quality_control_bounds=QualityControlBounds()), "strategic", time)
            for wid, worker in sorted(engine.workers.items()):
                if not worker.active_allocations:
                    request(wid, StrategicObservation(target_id=wid, allowed_actions=["worker_reassignment"],
                            current_configuration={"assigned_station_id": worker.assigned_station_id,
                                "compatible_station_ids": [sid for sid, st in sorted(engine.stations.items())
                                    if any(req.get("qualification") in worker.qualifications or req.get("worker_id") == wid
                                           for op in st.operations.values() for req in op.required_workers)]}), "strategic", time)
            # Routing/dispatch are attached to real pending Transport Orders.
            vehicles_claimed = 0
            for oid in list(engine.pending_transport_orders):
                order = engine.transport_orders[oid]
                routing_obs = engine._build_routing_observation(order.source_node_id, time, order.unit_id)
                if any(r.is_admissible for r in routing_obs.candidate_routes):
                    request(order.unit_id, routing_obs, "routing", time)
                dispatch = engine._build_dispatch_observation(time)
                if (dispatch.order_id == oid and dispatch.available_vehicles and vehicles_claimed == 0
                        and any(r.is_admissible for r in dispatch.candidate_routes)):
                    request(oid, dispatch, "dispatch", time)
                    vehicles_claimed += 1
        next_time = time + settings.interval_ns
        if next_time <= engine.cfg.episode.end_condition.max_time_ns:
            kernel.schedule(next_time, 100, "STUDY_SAMPLE")
    engine.kernel.register_handler("STUDY_SAMPLE", sample)
    engine.kernel.register_handler("STUDY_IDLE", idle)
    if not any(e[3].event_type == "STUDY_SAMPLE" for e in engine.kernel._queue):
        engine.kernel.schedule(engine.kernel.current_time_ns, 100, "STUDY_SAMPLE")


def generate_dataset(output_dir: Path, settings: StudySettings) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    source_root = Path(__file__).resolve().parents[3]
    source_files = sorted([*source_root.joinpath("src").rglob("*.py"),
                           *source_root.joinpath("ml").glob("*.py")])
    source_hashes = {str(p.relative_to(source_root)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in source_files}
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source_root,
                              capture_output=True, text=True)
    manifest: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "status": "incomplete",
        "channels": CHANNELS, "settings": asdict(settings), "held_out_combination": HELD_OUT,
        "episodes": [], "action_types": ACTION_TYPES,
        "provenance": {"python": platform.python_version(), "numpy": np.__version__,
                       "git_revision": revision.stdout.strip() or None,
                       "source_hashes": source_hashes, "source_hash": digest(source_hashes)}}
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    adapter = StudyObservationAdapter(settings.noise_scale, settings.missing_probability)
    index = 0
    effects: Counter[str] = Counter()
    def export_episode(engine: StudyEngine, config: SimulationConfig, eid: str, root: str,
                       split: str, branch: str, summary: Any) -> None:
        observations = [portable(o) for o in engine.study_observations]
        actions = [portable(a) for a in engine.action_evidence]
        for a in engine.action_evidence:
            if a.status == "applied":
                effects[a.action["action_type"]] += 1
        data = {"schema_version": SCHEMA_VERSION, "episode_id": eid, "branch_id": branch,
                "root_id": root, "seed": config.seed, "split": split, "graph": portable(graph_from_engine(engine)),
                "production_plan": [p.model_dump(mode="json") for p in config.production_plan],
                "observations": observations, "actions": actions}
        filename = eid + ".json"
        (output_dir / filename).write_text(json.dumps(data, allow_nan=False))
        (output_dir / (eid + ".labels.json")).write_text(json.dumps(engine.study_labels, allow_nan=False))
        (output_dir / (eid + ".config.json")).write_text(config.model_dump_json())
        manifest["episodes"].append({"episode_id": eid, "root_id": root, "seed": config.seed,
            "split": split, "path": filename, "hash": digest(data),
            "labels_hash": digest(engine.study_labels),
            "configuration_hash": digest(config.model_dump(mode="json")),
            "terminal_hash": digest(summary.to_dict())})
        manifest_path.write_text(json.dumps(manifest, indent=2))
    for split, count in (settings.counts or COUNTS).items():
        for _ in range(count):
            seed = settings.seed + index
            eid = f"episode-{seed}"
            config = research_configuration(settings, seed, split)
            engine = StudyEngine.create(config)
            assert isinstance(engine, StudyEngine)
            engine.decision_provider = ExplorationProvider(engine, split,
                "heuristic" if index % 3 == 0 else "random")
            graph = graph_from_engine(engine)
            install_sampling(engine, adapter, eid, settings)
            checkpoint = None
            prefix: list[Any] = []
            prefix_labels: list[dict[str, Any]] = []
            prefix_actions: list[TimedAction] = []
            if index % 3 == 0:
                engine.run(pause_at_ns=(settings.context - 1) * STEP_NS)
                checkpoint = engine.create_checkpoint()
                save_checkpoint(checkpoint, output_dir / (eid + ".checkpoint.json"))
                prefix = list(engine.study_observations)
                prefix_labels = copy.deepcopy(engine.study_labels)
                prefix_actions = list(engine.action_evidence)
            summary = engine.run()
            if engine.is_aborted:
                raise RuntimeError(f"Study episode aborted: {engine.abort_reason}")
            export_episode(engine, config, eid, eid, split, "main", summary)
            if checkpoint is not None:
                idle_machines = [mid for mid, m in sorted(checkpoint.domain_state.machines.items())
                                 if not m.active_allocations and not m.is_in_maintenance and not m.is_failed]
                if idle_machines:
                    mid = idle_machines[0]
                    modes = ("eco", "boost" if split == "unknown_combinations" or seed % 2 == 0 else "nominal")
                    for branch_number, mode in enumerate(modes):
                        branch = f"branch-{branch_number}"
                        child_id = eid + "-" + branch
                        child = StudyEngine.restore(checkpoint, config)
                        assert isinstance(child, StudyEngine)
                        child.study_observations = [replace(o, episode_id=child_id, branch_id=branch) for o in prefix]
                        child.study_labels = copy.deepcopy(prefix_labels)
                        child.action_evidence = list(prefix_actions)
                        child.configure_branch(branch)
                        child.decision_provider = ExplorationProvider(child, split, "heuristic")
                        action = MachineModeAction(target_id=mid, mode=mode)
                        request = DecisionRequest(request_id=f"intervention-{mid}", request_type="study",
                            target_id=mid, time_ns=checkpoint.simulated_time_ns,
                            observation=child._build_machine_observation(mid, checkpoint.simulated_time_ns),
                            action_schema="machine")
                        batch = DecisionBatch(batch_id=f"intervention-{branch}", episode_id=child_id,
                            branch_id=branch, time_ns=checkpoint.simulated_time_ns, requests=[request])
                        child._apply_actions_list(batch, [action])
                        install_sampling(child, adapter, child_id, settings, branch)
                        result = child.run()
                        export_episode(child, config, child_id, eid, split, branch, result)
            index += 1
    manifest.update(status="complete", applied_action_counts=dict(effects))
    manifest["dataset_hash"] = digest(manifest["episodes"])
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def verify_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads((path / "manifest.json").read_text())
    if manifest.get("status") != "complete" or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Incomplete or incompatible dataset")
    roots: dict[str, str] = {}
    seeds: dict[int, str] = {}
    for item in manifest["episodes"]:
        for mapping, key in ((roots, item["root_id"]), (seeds, item["seed"])):
            if key in mapping and mapping[key] != item["split"]:
                raise ValueError("Related episodes or seeds cross study splits")
            mapping[key] = item["split"]
        data = json.loads((path / item["path"]).read_text())
        if digest(data) != item["hash"]:
            raise ValueError("Dataset hash mismatch")
        observations = data["observations"]
        if any(o["episode_id"] != item["episode_id"] or o["branch_id"] != data["branch_id"]
               for o in observations):
            raise ValueError("Observation crosses episode or branch boundary")
        if any(b["time_ns"] - a["time_ns"] != STEP_NS for a, b in zip(observations, observations[1:])):
            raise ValueError("Broken observation time grid")
    return manifest

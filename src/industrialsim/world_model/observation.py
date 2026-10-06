"""The only adapter allowed to read simulator truth. Labels leave by a separate API."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from industrialsim.world_model.contracts import CHANNELS, PlantGraph, SensorReading, StudyObservation


def graph_from_engine(engine: Any) -> PlantGraph:
    nodes = sorted(engine.nodes_by_id)
    types = [engine.nodes_by_id[n].kind for n in nodes]
    capacities = [float(engine.nodes_by_id[n].capacity or 1) for n in nodes]
    machine_types = ["none"] * len(nodes)
    for mid, machine in sorted(engine.machines.items()):
        nodes.append(mid)
        types.append("machine")
        capacities.append(float(machine.capacity))
        # Classify by declared operation semantics, not an entity-ID embedding.
        operations = sorted({op.id for st in engine.stations.values()
                             for op in st.operations.values() if mid in op.required_machines})
        machine_types.append("|".join(operations) or "generic")
    for wid in sorted(engine.workers):
        nodes.append(wid)
        types.append("worker")
        capacities.append(float(engine.workers[wid].capacity))
        machine_types.append("none")
    indices = {name: i for i, name in enumerate(nodes)}
    edges = [(indices[r.source_node_id], indices[r.target_node_id]) for r in engine.routes]
    routes = {r.id: (indices[r.source_node_id], indices[r.target_node_id]) for r in engine.routes}
    for sid, station in sorted(engine.stations.items()):
        for mid in sorted({m for op in station.operations.values() for m in op.required_machines}):
            edges.extend(((indices[mid], indices[sid]), (indices[sid], indices[mid])))
    for wid, worker in sorted(engine.workers.items()):
        for sid, station in sorted(engine.stations.items()):
            if any(req.get("qualification") in worker.qualifications
                   or req.get("worker_id") == wid
                   for op in station.operations.values() for req in op.required_workers):
                edges.extend(((indices[wid], indices[sid]), (indices[sid], indices[wid])))
    return PlantGraph(tuple(nodes), tuple(types), tuple(edges), tuple(capacities),
                      tuple(machine_types), routes)


class StudyObservationAdapter:
    def __init__(self, noise_scale: float = 0.02, missing_probability: float = 0.02) -> None:
        if noise_scale < 0 or not 0 <= missing_probability <= 1:
            raise ValueError("Invalid sensor parameters")
        self.noise_scale = noise_scale
        self.missing_probability = missing_probability

    def _reading(self, engine: Any, entity: str, channel: str, unit: str,
                 signal: float, time_ns: int) -> SensorReading:
        # Explicit occurrence = sample timestamp: repeated reads and restored branches
        # get the same sensor realization without changing production randomness.
        random = engine.random_stream
        missing = random.draw_float("study_sensor_missing", entity, channel, time_ns) < self.missing_probability
        u1 = max(1e-12, random.draw_float("study_sensor_noise", entity, channel + ":a", time_ns))
        u2 = random.draw_float("study_sensor_noise", entity, channel + ":b", time_ns)
        noise = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
        value = signal + self.noise_scale * max(1.0, abs(signal)) * noise
        return SensorReading(time_ns, entity, channel, unit, None if missing else value, missing)

    def observe(self, engine: Any, graph: PlantGraph, episode_id: str, branch_id: str = "main",
                time_ns: int | None = None) -> StudyObservation:
        time = engine.kernel.current_time_ns if time_ns is None else time_ns
        rows = [[0.0] * len(CHANNELS) for _ in graph.node_ids]
        masks = [[False] * len(CHANNELS) for _ in graph.node_ids]
        readings: list[SensorReading] = []
        finding_objects = [f for u in engine.units.values() for f in u.findings if f.time_ns <= time]
        finding_counts = Counter(f.station_id for f in finding_objects)
        findings = [f.to_dict() for f in sorted(finding_objects, key=lambda f: (f.time_ns, f.station_id, f.unit_id))[-32:]]
        units_by_location: dict[str, list[Any]] = defaultdict(list)
        for unit in engine.units.values():
            if unit.process_state:
                units_by_location[unit.location].append(unit)
        terminal = [u for u in engine.units.values() if str(u.state) == "terminal"]
        metrics = {
            "good_output": float(sum(u.location != "scrapped" for u in terminal)),
            "scrap": float(sum(u.location == "scrapped" for u in terminal)),
            "wip": float(sum(str(u.state) not in ("created", "terminal") for u in engine.units.values())),
            "lateness_ns": float(sum(max(0, u.history[-1].time_ns - u.due_date_ns)
                                     for u in terminal if u.history and u.due_date_ns is not None)),
            "downtime_ns": float(sum(m.total_failed_time_ns + m.total_maintenance_time_ns
                                     for m in engine.machines.values())),
            "total_strategic_cost": float(engine.total_strategic_cost),
        }
        for i, nid in enumerate(graph.node_ids):
            def set_value(name: str, value: float) -> None:
                idx = CHANNELS.index(name)
                rows[i][idx], masks[i][idx] = value, True

            machine = engine.machines.get(nid)
            if machine is not None:
                busy = float(bool(machine.active_allocations))
                load = {"eco": 0.7, "nominal": 1.0, "boost": 1.3}.get(machine.operating_mode, 1.0)
                # Synthetic measurements, NOT copies of exact normalized health.
                signals = (45 + 35 * busy * load + 20 * (1 - machine.health),
                           0.1 + 0.8 * (1 - machine.health) + 0.15 * busy * load,
                           2 + 8 * busy * load, 4 + 2 * busy * load)
                for channel, unit, signal in zip(CHANNELS[:4], ("degC", "mm/s", "A", "bar"), signals):
                    reading = self._reading(engine, nid, channel, unit, signal, time)
                    readings.append(reading)
                    if reading.value is not None:
                        set_value(channel, reading.value)
                set_value("occupancy", busy)
                set_value("completed", float(machine.operations_completed))
            elif nid in engine.stations:
                station = engine.stations[nid]
                set_value("occupancy", float(station.is_busy or station.is_blocked))
                set_value("completed", float(station.operations_completed))
                local_units = units_by_location[nid]
                if local_units:
                    signal = sum(sum(u.process_state.values()) / len(u.process_state)
                                 for u in local_units) / len(local_units)
                    reading = self._reading(engine, nid, "process_signal", "relative", signal, time)
                    readings.append(reading)
                    if reading.value is not None:
                        set_value("process_signal", reading.value)
                set_value("findings", float(finding_counts[nid]))
            elif nid in engine.buffers:
                set_value("occupancy", float(len(engine.buffers[nid].occupants)))
            elif nid in engine.workers:
                set_value("occupancy", float(len(engine.workers[nid].active_allocations)))
            # Aggregate targets reside at one deterministic source node, avoiding
            # overweighting plant metrics as the graph grows.
            if i == 0:
                for name, value in metrics.items():
                    set_value(name, value)
        return StudyObservation(episode_id, branch_id, time, tuple(map(tuple, rows)),
                                tuple(map(tuple, masks)), tuple(readings), tuple(findings))

    def labels(self, engine: Any, injected_causes: list[str] | None = None) -> dict[str, Any]:
        return {"health_state": {mid: m.health for mid, m in engine.machines.items()},
                "process_state": {uid: dict(u.process_state) for uid, u in engine.units.items()},
                "quality_state": {uid: u.quality_state for uid, u in engine.units.items()},
                "unit_locations": {uid: u.location for uid, u in engine.units.items()},
                "injected_causes": injected_causes or []}

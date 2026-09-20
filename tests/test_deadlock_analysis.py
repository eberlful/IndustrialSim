from __future__ import annotations

import json
import pytest
from industrialsim.application import EpisodeEngine, validate_config
from industrialsim.deadlock import (
    DeadlockDiagnosis,
    WaitEdge,
    WaitForGraph,
    analyze_deadlock,
    build_wait_for_graph,
)
from industrialsim.domain import ProductionUnitState


def test_wait_edge_and_diagnosis_serialization() -> None:
    edge = WaitEdge(
        from_entity="u-01",
        to_entity="buf-B",
        resource="buf-B",
        wait_type="buffer_capacity",
        holder="u-02",
        reason="Buffer 'buf-B' at capacity (1/1)",
    )
    edge_dict = edge.to_dict()
    assert edge_dict["from_entity"] == "u-01"
    assert edge_dict["to_entity"] == "buf-B"
    assert edge_dict["waiter"] == "u-01"
    assert edge_dict["holder"] == "u-02"
    assert edge_dict["resource"] == "buf-B"
    assert edge_dict["wait_type"] == "buffer_capacity"

    diag = DeadlockDiagnosis(
        deadlock_type="buffer_cycle",
        involved_entities=["buf-A", "buf-B", "u-01", "u-02"],
        capacities={"buf-A": {"capacity": 1, "occupancy": 1}, "buf-B": {"capacity": 1, "occupancy": 1}},
        ownership={"buf-A": ["u-01"], "buf-B": ["u-02"]},
        wait_edges=[edge_dict],
        cycle=["u-01", "buf-B", "u-02", "buf-A", "u-01"],
        reason="Deadlock detected: circular wait on buffer capacity",
        simulated_time_ns=10_000_000_000,
    )
    diag_dict = diag.to_dict()
    assert diag_dict["deadlock_type"] == "buffer_cycle"
    assert "u-01" in diag_dict["involved_entities"]
    # Check JSON serializability
    dumped = json.dumps(diag_dict)
    assert "buffer_cycle" in dumped


def test_buffer_cycle_deadlock_detection() -> None:
    # Setup two buffers in a loop, capacity 1 each.
    # Unit 1 is in buf-A wanting to go to buf-B.
    # Unit 2 is in buf-B wanting to go to buf-A.
    yaml_config = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0s
  end_condition:
    type: "all_units_terminal"
material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "buf-A"
      kind: "buffer"
      capacity: 1
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "buf-B"
      kind: "buffer"
      capacity: 1
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "sink-1"
      kind: "sink"
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
  routes:
    - id: "r-src-A"
      source_node_id: "src-1"
      source_port_id: "out"
      target_node_id: "buf-A"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-src-sink"
      source_node_id: "src-1"
      source_port_id: "out"
      target_node_id: "sink-1"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-A-B"
      source_node_id: "buf-A"
      source_port_id: "out"
      target_node_id: "buf-B"
      target_port_id: "in"
      transit_time: "5s"
    - id: "r-B-A"
      source_node_id: "buf-B"
      source_port_id: "out"
      target_node_id: "buf-A"
      target_port_id: "in"
      transit_time: "5s"
production_units:
  - id: "u-A"
    variant: "v-A"
  - id: "u-B"
    variant: "v-B"
"""
    val = validate_config(yaml_config)
    assert val.is_valid, val.errors
    assert val.config is not None
    engine = EpisodeEngine.create(val.config)

    # Place u-A into buf-A, and u-B into buf-B
    engine.units["u-A"].state = ProductionUnitState.IN_BUFFER
    engine.units["u-A"].location = "buf-A"
    engine.buffers["buf-A"].add_unit("u-A")

    engine.units["u-B"].state = ProductionUnitState.IN_BUFFER
    engine.units["u-B"].location = "buf-B"
    engine.buffers["buf-B"].add_unit("u-B")

    # Create transport orders for both units
    engine._create_transport_order("u-A", "buf-A", engine.kernel.current_time_ns)
    engine._create_transport_order("u-B", "buf-B", engine.kernel.current_time_ns)

    # Now neither can depart because candidate target nodes are full!
    wfg = build_wait_for_graph(engine)
    assert len(wfg.edges) >= 2

    diagnosis = analyze_deadlock(engine)
    assert diagnosis is not None
    assert diagnosis.deadlock_type == "buffer_cycle"
    assert set(["buf-A", "buf-B", "u-A", "u-B"]).issubset(set(diagnosis.involved_entities))
    assert "buf-A" in diagnosis.capacities
    assert "buf-B" in diagnosis.capacities
    assert diagnosis.ownership["buf-A"] == ["u-A"]
    assert diagnosis.ownership["buf-B"] == ["u-B"]
    assert len(diagnosis.wait_edges) >= 2


def test_ordinary_finite_waiting_is_not_deadlock() -> None:
    # Station is actively running an operation with scheduled COMPLETE_OPERATION.
    # A unit in an upstream buffer is waiting for the station to become free.
    # This must NOT be classified as deadlock!
    yaml_config = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0s
  end_condition:
    type: "all_units_terminal"
material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "buf-1"
      kind: "buffer"
      capacity: 2
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "st-1"
      kind: "station"
      operations:
        - id: "op-1"
          duration: "50s"
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "sink-1"
      kind: "sink"
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
  routes:
    - id: "r-src-buf"
      source_node_id: "src-1"
      source_port_id: "out"
      target_node_id: "buf-1"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-buf-st"
      source_node_id: "buf-1"
      source_port_id: "out"
      target_node_id: "st-1"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-st-sink"
      source_node_id: "st-1"
      source_port_id: "out"
      target_node_id: "sink-1"
      target_port_id: "in"
      transit_time: "1s"
production_units:
  - id: "u-running"
    variant: "v-1"
  - id: "u-waiting"
    variant: "v-1"
"""
    val = validate_config(yaml_config)
    assert val.is_valid, val.errors
    assert val.config is not None
    engine = EpisodeEngine.create(val.config)

    # u-running is in st-1 with active operation
    st = engine.stations["st-1"]
    st.start_operation("u-running", "op-1", 0)
    engine.units["u-running"].state = ProductionUnitState.IN_STATION
    engine.units["u-running"].location = "st-1"
    engine.active_operations["st-1"] = {
        "station_id": "st-1",
        "unit_id": "u-running",
        "op_id": "op-1",
        "op_index": 0,
        "start_time_ns": 0,
        "remaining_duration_ns": 50_000_000_000,
        "machines": [],
        "workers": [],
        "token": 1,
    }
    # Schedule COMPLETE_OPERATION in kernel
    from industrialsim.kernel import EventPriority
    engine.kernel.schedule(
        time_ns=50_000_000_000,
        priority=EventPriority.COMPLETION,
        event_type="COMPLETE_OPERATION",
        payload={"unit_id": "u-running", "station_id": "st-1", "op_index": 0, "token": 1},
    )

    # u-waiting is in buf-1 waiting for st-1
    engine.units["u-waiting"].state = ProductionUnitState.IN_BUFFER
    engine.units["u-waiting"].location = "buf-1"
    engine.buffers["buf-1"].add_unit("u-waiting")
    engine._create_transport_order("u-waiting", "buf-1", 0)

    # Deadlock analysis must recognize this as ordinary finite waiting!
    diagnosis = analyze_deadlock(engine)
    assert diagnosis is None


def test_resource_cycle_deadlock_detection() -> None:
    # Station A holds u-A, waiting for mach-B.
    # mach-B is allocated to Station B (holding u-B).
    # Station B finished op, blocked after service waiting for Station A.
    # Station A cannot accept u-B because it holds u-A.
    yaml_config = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0s
  end_condition:
    type: "all_units_terminal"
material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "st-A"
      kind: "station"
      operations:
        - id: "op-A"
          duration: "10s"
          required_machines: ["mach-B"]
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "st-B"
      kind: "station"
      operations:
        - id: "op-B"
          duration: "10s"
          required_machines: ["mach-B"]
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "sink-1"
      kind: "sink"
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
  routes:
    - id: "r-src-sink"
      source_node_id: "src-1"
      source_port_id: "out"
      target_node_id: "sink-1"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-A-B"
      source_node_id: "st-A"
      source_port_id: "out"
      target_node_id: "st-B"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-B-A"
      source_node_id: "st-B"
      source_port_id: "out"
      target_node_id: "st-A"
      target_port_id: "in"
      transit_time: "1s"
machines:
  - id: "mach-B"
    capacity: 1
production_units:
  - id: "u-A"
    variant: "v-A"
  - id: "u-B"
    variant: "v-B"
"""
    val = validate_config(yaml_config)
    assert val.is_valid, val.errors
    assert val.config is not None
    engine = EpisodeEngine.create(val.config)

    # st-A holds u-A and is waiting in resource_waiters for mach-B
    st_A = engine.stations["st-A"]
    st_A.current_unit_id = "u-A"
    engine.units["u-A"].state = ProductionUnitState.IN_STATION
    engine.units["u-A"].location = "st-A"
    engine.resource_waiters.append({
        "station_id": "st-A",
        "unit_id": "u-A",
        "op_index": 0,
        "waiting_since_ns": 0,
        "remaining_duration_ns": 10_000_000_000,
    })

    # mach-B is allocated to st-B with u-B
    st_B = engine.stations["st-B"]
    st_B.current_unit_id = "u-B"
    st_B.is_blocked = True
    st_B.blocked_unit_id = "u-B"
    engine.units["u-B"].state = ProductionUnitState.BLOCKED
    engine.units["u-B"].location = "st-B"
    engine.machines["mach-B"].allocate("st-B", "u-B", "op-B", 0)

    # st-B wants to route u-B to st-A
    engine._create_transport_order("u-B", "st-B", 0)

    diagnosis = analyze_deadlock(engine)
    assert diagnosis is not None
    assert diagnosis.deadlock_type == "resource_cycle"
    assert "mach-B" in diagnosis.involved_entities
    assert set(["st-A", "st-B", "u-A", "u-B"]).issubset(set(diagnosis.involved_entities))
    assert "mach-B" in diagnosis.capacities
    assert diagnosis.capacities["mach-B"]["capacity"] == 1
    assert len(diagnosis.wait_edges) >= 2


def test_logistics_cycle_deadlock_detection() -> None:
    # Two vehicles traversing opposing capacity-constrained routes with crossed destinations
    yaml_config = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0s
  end_condition:
    type: "all_units_terminal"
material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "buf-1"
      kind: "buffer"
      capacity: 10
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "buf-2"
      kind: "buffer"
      capacity: 10
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "sink-1"
      kind: "sink"
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
  routes:
    - id: "r-src-sink"
      source_node_id: "src-1"
      source_port_id: "out"
      target_node_id: "sink-1"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-1-2"
      source_node_id: "buf-1"
      source_port_id: "out"
      target_node_id: "buf-2"
      target_port_id: "in"
      transit_time: "10s"
      capacity: 1
    - id: "r-2-1"
      source_node_id: "buf-2"
      source_port_id: "out"
      target_node_id: "buf-1"
      target_port_id: "in"
      transit_time: "10s"
      capacity: 1
vehicles:
  - id: "veh-1"
    initial_location: "buf-1"
  - id: "veh-2"
    initial_location: "buf-2"
production_units:
  - id: "u-1"
    variant: "v-1"
  - id: "u-2"
    variant: "v-2"
"""
    val = validate_config(yaml_config)
    assert val.is_valid, val.errors
    assert val.config is not None
    engine = EpisodeEngine.create(val.config)

    # Put u-1 in buf-1 and u-2 in buf-2
    engine.units["u-1"].state = ProductionUnitState.IN_BUFFER
    engine.units["u-1"].location = "buf-1"
    engine.buffers["buf-1"].add_unit("u-1")

    engine.units["u-2"].state = ProductionUnitState.IN_BUFFER
    engine.units["u-2"].location = "buf-2"
    engine.buffers["buf-2"].add_unit("u-2")

    # Both routes at capacity
    engine.active_route_occupancy["r-1-2"] = 1
    engine.active_route_occupancy["r-2-1"] = 1

    # veh-1 on r-1-2 heading to buf-2, but assigned next route is r-2-1
    v1 = engine.vehicles["veh-1"]
    v1.current_route_id = "r-1-2"
    to1 = engine._create_transport_order("u-1", "buf-1", 0)
    to1.assigned_route_id = "r-2-1"
    v1.current_order_id = to1.id
    v1.current_unit_id = "u-1"

    # veh-2 on r-2-1 heading to buf-1, but assigned next route is r-1-2
    v2 = engine.vehicles["veh-2"]
    v2.current_route_id = "r-2-1"
    to2 = engine._create_transport_order("u-2", "buf-2", 0)
    to2.assigned_route_id = "r-1-2"
    v2.current_order_id = to2.id
    v2.current_unit_id = "u-2"

    diagnosis = analyze_deadlock(engine)
    assert diagnosis is not None
    assert diagnosis.deadlock_type == "logistics_cycle"
    assert "r-1-2" in diagnosis.cycle or "r-2-1" in diagnosis.cycle
    assert "veh-1" in diagnosis.involved_entities
    assert "veh-2" in diagnosis.involved_entities


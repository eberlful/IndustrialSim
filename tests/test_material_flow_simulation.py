import pytest
from industrialsim.application import run_episode


BLOCKING_SCENARIO_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

plant:
  id: "plant-1"
  name: "Assembly Plant"
  areas:
    - id: "area-1"
      name: "Main Area"
      halls:
        - id: "hall-1"
          name: "Main Hall"

material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      hall_id: "hall-1"
      output_ports:
        - id: "p-out"
          port_type: "vehicle"
          direction: "output"
    - id: "st-1"
      kind: "station"
      hall_id: "hall-1"
      output_capacity: 0
      operations:
        - id: "op-fast"
          duration: "2s"
      input_ports:
        - id: "p-in"
          port_type: "vehicle"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "vehicle"
          direction: "output"
    - id: "buf-1"
      kind: "buffer"
      hall_id: "hall-1"
      capacity: 1
      input_ports:
        - id: "p-in"
          port_type: "vehicle"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "vehicle"
          direction: "output"
    - id: "st-2"
      kind: "station"
      hall_id: "hall-1"
      output_capacity: 0
      operations:
        - id: "op-slow"
          duration: "10s"
      input_ports:
        - id: "p-in"
          port_type: "vehicle"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "vehicle"
          direction: "output"
    - id: "snk-1"
      kind: "sink"
      hall_id: "hall-1"
      input_ports:
        - id: "p-in"
          port_type: "vehicle"
          direction: "input"
  routes:
    - id: "r-src-st1"
      source_node_id: "src-1"
      source_port_id: "p-out"
      target_node_id: "st-1"
      target_port_id: "p-in"
    - id: "r-st1-buf"
      source_node_id: "st-1"
      source_port_id: "p-out"
      target_node_id: "buf-1"
      target_port_id: "p-in"
    - id: "r-buf-st2"
      source_node_id: "buf-1"
      source_port_id: "p-out"
      target_node_id: "st-2"
      target_port_id: "p-in"
    - id: "r-st2-snk"
      source_node_id: "st-2"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"

production_units:
  - id: "unit-1"
    variant: "sedan"
    release_time: "0s"
  - id: "unit-2"
    variant: "sedan"
    release_time: "0s"
  - id: "unit-3"
    variant: "sedan"
    release_time: "0s"
"""


def test_material_flow_end_to_end_and_blocking_after_service() -> None:
    summary = run_episode(BLOCKING_SCENARIO_YAML)

    assert summary.status == "completed"
    assert len(summary.production_units) == 3

    # All units must reach terminal state
    for u in summary.production_units:
        assert u.state == "terminal"
        assert u.location == "terminal"

    # Verify unit location invariant: at no point can location be None or invalid
    for u in summary.production_units:
        assert len(u.history) >= 4
        for record in u.history:
            assert "location" in record
            assert record["location"] in {
                "src-1",
                "st-1",
                "buf-1",
                "st-2",
                "snk-1",
                "terminal",
                "r-src-st1",
                "r-st1-buf",
                "r-buf-st2",
                "r-st2-snk",
            }

    # Station 1 processes fast (2s per unit).
    # Station 2 processes slow (10s per unit).
    # Buffer 1 has capacity 1.
    # Unit 1: arrives at st-1 at 0s, finishes at 2s, enters buf-1 at 2s, enters st-2 at 2s, finishes st-2 at 12s.
    # Unit 2: enters st-1 at 2s, finishes at 4s. st-2 is busy with unit-1 until 12s.
    # buf-1 is empty at 2s (unit-1 moved to st-2 immediately), so unit-2 enters buf-1 at 4s.
    # Unit 3: enters st-1 at 4s, finishes at 6s.
    # At 6s, buf-1 is occupied by unit-2! st-2 is busy with unit-1 until 12s!
    # Therefore, unit-3 cannot leave st-1 at 6s!
    # st-1 must be BLOCKED after service from 6s until 12s (6 seconds of blocking).
    st1 = next(s for s in summary.stations if s.id == "st-1")
    assert st1.operations_completed == 3
    assert st1.total_busy_time_ns == 6_000_000_000  # 3 * 2s = 6s
    assert st1.total_blocked_time_ns > 0  # Demonstrates blocking-after-service backpressure!
    assert st1.total_blocked_time_ns == 6_000_000_000  # Blocked from 6s to 12s = 6s


def test_station_output_capacity_relieves_station() -> None:
    # Adding output_capacity=1 to st-1 allows unit-3 to move into st-1:output at 6s,
    # relieving the main station processing area.
    yaml_with_output_cap = BLOCKING_SCENARIO_YAML.replace(
        'output_capacity: 0\n      operations:\n        - id: "op-fast"',
        'output_capacity: 1\n      operations:\n        - id: "op-fast"',
    )

    summary = run_episode(yaml_with_output_cap)
    assert summary.status == "completed"

    st1 = next(s for s in summary.stations if s.id == "st-1")
    # With output capacity = 1, st-1 itself is not blocked during unit-3's wait;
    # unit-3 moved to st-1:output buffer!
    assert st1.total_blocked_time_ns == 0
    u3 = next(u for u in summary.production_units if u.id == "unit-3")
    assert u3.state == "terminal"


def test_station_multiple_operations_executed_in_order() -> None:
    multi_op_yaml = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "st-multi"
      kind: "station"
      operations:
        - id: "op-step-1"
          duration: "3s"
        - id: "op-step-2"
          duration: "4s"
      input_ports:
        - id: "p-in"
          port_type: "part"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "snk-1"
      kind: "sink"
      input_ports:
        - id: "p-in"
          port_type: "part"
          direction: "input"
  routes:
    - id: "r1"
      source_node_id: "src-1"
      source_port_id: "p-out"
      target_node_id: "st-multi"
      target_port_id: "p-in"
    - id: "r2"
      source_node_id: "st-multi"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"

production_units:
  - id: "unit-alpha"
    variant: "sedan"
    release_time: "0s"
"""
    summary = run_episode(multi_op_yaml)
    assert summary.status == "completed"
    # op-step-1 (3s) + op-step-2 (4s) = 7s total
    assert summary.simulated_time_ns == 7_000_000_000

    u = summary.production_units[0]
    assert u.state == "terminal"
    # Verify operations were executed
    ops_in_history = [h.get("operation_id") for h in u.history if h.get("operation_id")]
    assert ops_in_history == ["op-step-1", "op-step-2"]


def test_material_flow_multiple_sources() -> None:
    multi_source_yaml = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

material_flow:
  nodes:
    - id: "src-A"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "src-B"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "snk-1"
      kind: "sink"
      input_ports:
        - id: "p-in"
          port_type: "part"
          direction: "input"
  routes:
    - id: "r-A"
      source_node_id: "src-A"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"
    - id: "r-B"
      source_node_id: "src-B"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"

production_units:
  - id: "unit-from-A"
    variant: "sedan"
    source_id: "src-A"
    release_time: "0s"
  - id: "unit-from-B"
    variant: "suv"
    source_id: "src-B"
    release_time: "0s"
"""
    summary = run_episode(multi_source_yaml)
    assert summary.status == "completed"
    assert len(summary.production_units) == 2
    u_a = next(u for u in summary.production_units if u.id == "unit-from-A")
    u_b = next(u for u in summary.production_units if u.id == "unit-from-B")
    assert u_a.history[0]["location"] == "src-A"
    assert u_b.history[0]["location"] == "src-B"



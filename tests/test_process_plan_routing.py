from __future__ import annotations

import pytest

from industrialsim.application import run_episode, validate_config
from industrialsim.config import ProcessPlanConfig, ProcessPlanStepConfig


def test_process_plan_validation() -> None:
    # 1. Invalid: compatible station does not exist
    invalid_station_yaml = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
stations:
  - id: "st-1"
    operations:
      - id: "op-1"
        duration: "10s"
production_plan:
  - variant: "sedan"
    quantity: 1
process_plans:
  - variant: "sedan"
    steps:
      - operation_id: "op-1"
        compatible_stations: ["unknown-station"]
"""
    val1 = validate_config(invalid_station_yaml)
    assert not val1.is_valid
    assert any("unknown-station" in err for err in val1.errors)

    # 2. Invalid: station exists but does not offer required operation
    invalid_op_yaml = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
stations:
  - id: "st-1"
    operations:
      - id: "op-1"
        duration: "10s"
production_plan:
  - variant: "sedan"
    quantity: 1
process_plans:
  - variant: "sedan"
    steps:
      - operation_id: "op-2"
        compatible_stations: ["st-1"]
"""
    val2 = validate_config(invalid_op_yaml)
    assert not val2.is_valid
    assert any("op-2" in err for err in val2.errors)


def test_two_variants_routed_through_distinct_process_plans() -> None:
    yaml_content = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
material_flow:
  nodes:
    - id: "src"
      kind: "source"
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-weld"
      kind: "station"
      operations:
        - id: "op-weld"
          duration: "10s"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-paint"
      kind: "station"
      operations:
        - id: "op-paint"
          duration: "15s"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-trim"
      kind: "station"
      operations:
        - id: "op-trim"
          duration: "20s"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "snk"
      kind: "sink"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
  routes:
    - id: "r-src-weld"
      source_node_id: "src"
      source_port_id: "out"
      target_node_id: "st-weld"
      target_port_id: "in"
    - id: "r-weld-paint"
      source_node_id: "st-weld"
      source_port_id: "out"
      target_node_id: "st-paint"
      target_port_id: "in"
    - id: "r-weld-trim"
      source_node_id: "st-weld"
      source_port_id: "out"
      target_node_id: "st-trim"
      target_port_id: "in"
    - id: "r-paint-snk"
      source_node_id: "st-paint"
      source_port_id: "out"
      target_node_id: "snk"
      target_port_id: "in"
    - id: "r-trim-snk"
      source_node_id: "st-trim"
      source_port_id: "out"
      target_node_id: "snk"
      target_port_id: "in"
production_plan:
  - id: "sedan-1"
    variant: "sedan"
    quantity: 1
    release_time: 0
  - id: "suv-1"
    variant: "suv"
    quantity: 1
    release_time: "15s"
process_plans:
  - variant: "sedan"
    steps:
      - operation_id: "op-weld"
        compatible_stations: ["st-weld"]
      - operation_id: "op-paint"
        compatible_stations: ["st-paint"]
  - variant: "suv"
    steps:
      - operation_id: "op-weld"
        compatible_stations: ["st-weld"]
      - operation_id: "op-trim"
        compatible_stations: ["st-trim"]
"""
    summary = run_episode(yaml_content)
    assert summary.status == "completed"
    assert len(summary.production_units) == 2

    sedan = next(u for u in summary.production_units if u.variant == "sedan")
    suv = next(u for u in summary.production_units if u.variant == "suv")

    # Verify sedan visited weld and paint
    sedan_ops = [h["operation_id"] for h in sedan.history if h.get("operation_id")]
    assert sedan_ops == ["op-weld", "op-paint"]

    # Verify SUV visited weld and trim
    suv_ops = [h["operation_id"] for h in suv.history if h.get("operation_id")]
    assert suv_ops == ["op-weld", "op-trim"]


def test_routing_policy_selects_among_compatible_station_alternatives() -> None:
    yaml_content = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
material_flow:
  nodes:
    - id: "src"
      kind: "source"
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-weld-1"
      kind: "station"
      operations:
        - id: "op-weld"
          duration: "20s"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-weld-2"
      kind: "station"
      operations:
        - id: "op-weld"
          duration: "20s"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "snk"
      kind: "sink"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
  routes:
    - id: "r-src-weld1"
      source_node_id: "src"
      source_port_id: "out"
      target_node_id: "st-weld-1"
      target_port_id: "in"
    - id: "r-src-weld2"
      source_node_id: "src"
      source_port_id: "out"
      target_node_id: "st-weld-2"
      target_port_id: "in"
    - id: "r-weld1-snk"
      source_node_id: "st-weld-1"
      source_port_id: "out"
      target_node_id: "snk"
      target_port_id: "in"
    - id: "r-weld2-snk"
      source_node_id: "st-weld-2"
      source_port_id: "out"
      target_node_id: "snk"
      target_port_id: "in"
production_plan:
  - id: "car-A"
    variant: "sedan"
    quantity: 1
    release_time: 0
  - id: "car-B"
    variant: "sedan"
    quantity: 1
    release_time: 0
process_plans:
  - variant: "sedan"
    steps:
      - operation_id: "op-weld"
        compatible_stations: ["st-weld-1", "st-weld-2"]
"""
    summary1 = run_episode(yaml_content)
    summary2 = run_episode(yaml_content)

    assert summary1.status == "completed"
    assert summary1.result_hash == summary2.result_hash

    # Car-A went to st-weld-1, Car-B went to st-weld-2 because st-weld-1 was occupied
    car_a = next(u for u in summary1.production_units if u.id == "car-A-1")
    car_b = next(u for u in summary1.production_units if u.id == "car-B-1")

    car_a_stations = [h["station_id"] for h in car_a.history if h.get("station_id")]
    car_b_stations = [h["station_id"] for h in car_b.history if h.get("station_id")]

    assert "st-weld-1" in car_a_stations
    assert "st-weld-2" in car_b_stations

    # Both completed at 20s in parallel instead of sequentially at 40s
    assert summary1.simulated_time_ns == 20_000_000_000

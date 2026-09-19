from __future__ import annotations

import pytest

from industrialsim.application import EpisodeEngine, create_checkpoint, restore_checkpoint, run_episode


def test_end_to_end_variants_rework_scrap_and_undetected() -> None:
    """Demonstrate both variants, undetected defects, detected defects, rework, and Scrap.

    - Unit 1 (sedan-nominal): Nominal sedan passes fab and inspection to sink.
    - Unit 2 (sedan-rework): Sedan develops a weld defect, is detected at inspection,
      routed to rework station, repaired, re-inspected, and completed at sink.
    - Unit 3 (suv-scrap): SUV develops a frame crack, is detected at inspection,
      and is scrapped according to the SUV disposition policy.
    - Unit 4 (suv-undetected): SUV develops a flaw, but sensitivity is 0,
      so the defect passes undetected to sink with nominal findings.
    """
    yaml_content = """
schema_version: "1.0"
seed: 12345
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
material_flow:
  nodes:
    - id: "src"
      kind: "source"
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-prep"
      kind: "station"
      operations:
        - id: "op-prep"
          duration: "5s"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-fab-sedan"
      kind: "station"
      operations:
        - id: "op-fab-sedan"
          duration: "10s"
          defect_probability: 1.0
          defect_name: "weld_defect"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-fab-suv"
      kind: "station"
      operations:
        - id: "op-fab-suv"
          duration: "12s"
          defect_probability: 1.0
          defect_name: "frame_defect"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-inspect"
      kind: "station"
      operations:
        - id: "op-inspect-sedan"
          duration: "4s"
          inspection:
            sensitivity: 1.0
            false_positive_rate: 0.0
            disposition_on_defect: "rework"
            rework_station_id: "st-rework"
            rework_operation_id: "op-rework"
            max_reworks: 1
        - id: "op-inspect-suv"
          duration: "4s"
          inspection:
            sensitivity: 1.0
            false_positive_rate: 0.0
            disposition_on_defect: "scrap"
        - id: "op-inspect-stealth"
          duration: "4s"
          inspection:
            sensitivity: 0.0
            false_positive_rate: 0.0
            disposition_on_defect: "scrap"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-rework"
      kind: "station"
      operations:
        - id: "op-rework"
          duration: "8s"
          restores_quality: true
          rework_success_probability: 1.0
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "snk"
      kind: "sink"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
  routes:
    - id: "r-src-prep"
      source_node_id: "src"
      source_port_id: "out"
      target_node_id: "st-prep"
      target_port_id: "in"
    - id: "r-prep-fab-sedan"
      source_node_id: "st-prep"
      source_port_id: "out"
      target_node_id: "st-fab-sedan"
      target_port_id: "in"
    - id: "r-prep-fab-suv"
      source_node_id: "st-prep"
      source_port_id: "out"
      target_node_id: "st-fab-suv"
      target_port_id: "in"
    - id: "r-fab-sedan-inspect"
      source_node_id: "st-fab-sedan"
      source_port_id: "out"
      target_node_id: "st-inspect"
      target_port_id: "in"
    - id: "r-fab-suv-inspect"
      source_node_id: "st-fab-suv"
      source_port_id: "out"
      target_node_id: "st-inspect"
      target_port_id: "in"
    - id: "r-inspect-rework"
      source_node_id: "st-inspect"
      source_port_id: "out"
      target_node_id: "st-rework"
      target_port_id: "in"
    - id: "r-rework-inspect"
      source_node_id: "st-rework"
      source_port_id: "out"
      target_node_id: "st-inspect"
      target_port_id: "in"
    - id: "r-inspect-snk"
      source_node_id: "st-inspect"
      source_port_id: "out"
      target_node_id: "snk"
      target_port_id: "in"
production_plan:
  - id: "sedan"
    variant: "sedan"
    quantity: 1
    release_time: "0s"
  - id: "suv"
    variant: "suv"
    quantity: 1
    release_time: "20s"
  - id: "suv-stealth"
    variant: "suv-stealth"
    quantity: 1
    release_time: "40s"
process_plans:
  - variant: "sedan"
    steps:
      - operation_id: "op-prep"
        compatible_stations: ["st-prep"]
      - operation_id: "op-fab-sedan"
        compatible_stations: ["st-fab-sedan"]
      - operation_id: "op-inspect-sedan"
        compatible_stations: ["st-inspect"]
  - variant: "suv"
    steps:
      - operation_id: "op-prep"
        compatible_stations: ["st-prep"]
      - operation_id: "op-fab-suv"
        compatible_stations: ["st-fab-suv"]
      - operation_id: "op-inspect-suv"
        compatible_stations: ["st-inspect"]
  - variant: "suv-stealth"
    steps:
      - operation_id: "op-prep"
        compatible_stations: ["st-prep"]
      - operation_id: "op-fab-suv"
        compatible_stations: ["st-fab-suv"]
      - operation_id: "op-inspect-stealth"
        compatible_stations: ["st-inspect"]
"""
    summary = run_episode(yaml_content)
    assert summary.status == "completed"
    assert len(summary.production_units) == 3

    units_by_id = {u.id: u for u in summary.production_units}
    sedan_unit = units_by_id["sedan-1"]
    suv_unit = units_by_id["suv-1"]
    stealth_unit = units_by_id["suv-stealth-1"]

    # Sedan: completes through rework cycle
    assert sedan_unit.state == "terminal"
    assert sedan_unit.location == "terminal"
    assert sedan_unit.quality_state == "nominal"
    assert len(sedan_unit.findings) == 2
    assert sedan_unit.findings[0]["disposition"] == "rework"
    assert sedan_unit.findings[1]["disposition"] == "pass"

    # SUV: defect detected and scrapped at inspection station
    assert suv_unit.state == "terminal"
    assert suv_unit.location == "terminal"
    assert suv_unit.quality_state == "frame_defect"
    assert len(suv_unit.findings) == 1
    assert suv_unit.findings[0]["disposition"] == "scrap"

    # SUV-stealth: defect passes undetected to sink
    assert stealth_unit.state == "terminal"
    assert stealth_unit.location == "terminal"
    assert stealth_unit.quality_state == "frame_defect"
    assert len(stealth_unit.findings) == 1
    assert stealth_unit.findings[0]["result"] == "nominal"
    assert stealth_unit.findings[0]["disposition"] == "pass"

    # Inspect station scrapped count is 1 (for the SUV only)
    inspect_st = next(s for s in summary.stations if s.id == "st-inspect")
    assert inspect_st.scrapped_count == 1


def test_rework_cycle_restores_and_reinspected() -> None:
    """Test explicit rework cycle: unit is inspected, sent to rework, repaired, and re-inspected."""
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
    - id: "st-fab"
      kind: "station"
      operations:
        - id: "op-fab"
          duration: "10s"
          defect_probability: 1.0
          defect_name: "surface_scratch"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-inspect"
      kind: "station"
      operations:
        - id: "op-inspect"
          duration: "5s"
          inspection:
            sensitivity: 1.0
            false_positive_rate: 0.0
            disposition_on_defect: "rework"
            rework_station_id: "st-rework"
            rework_operation_id: "op-buff"
            max_reworks: 1
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-rework"
      kind: "station"
      operations:
        - id: "op-buff"
          duration: "7s"
          restores_quality: true
          rework_success_probability: 1.0
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "snk"
      kind: "sink"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
  routes:
    - id: "r-src-fab"
      source_node_id: "src"
      source_port_id: "out"
      target_node_id: "st-fab"
      target_port_id: "in"
    - id: "r-fab-inspect"
      source_node_id: "st-fab"
      source_port_id: "out"
      target_node_id: "st-inspect"
      target_port_id: "in"
    - id: "r-inspect-rework"
      source_node_id: "st-inspect"
      source_port_id: "out"
      target_node_id: "st-rework"
      target_port_id: "in"
    - id: "r-rework-inspect"
      source_node_id: "st-rework"
      source_port_id: "out"
      target_node_id: "st-inspect"
      target_port_id: "in"
    - id: "r-inspect-snk"
      source_node_id: "st-inspect"
      source_port_id: "out"
      target_node_id: "snk"
      target_port_id: "in"
production_plan:
  - id: "sedan-1"
    variant: "sedan"
    quantity: 1
process_plans:
  - variant: "sedan"
    steps:
      - operation_id: "op-fab"
        compatible_stations: ["st-fab"]
      - operation_id: "op-inspect"
        compatible_stations: ["st-inspect"]
"""
    summary = run_episode(yaml_content)
    assert summary.status == "completed"
    assert len(summary.production_units) == 1

    unit = summary.production_units[0]
    # Unit completed at sink
    assert unit.location == "terminal"
    assert unit.state == "terminal"
    assert unit.quality_state == "nominal"

    # Findings should show first inspection detected defect, second inspection passed
    assert len(unit.findings) == 2
    f1, f2 = unit.findings[0], unit.findings[1]
    assert f1["result"] == "defect_detected"
    assert f1["disposition"] == "rework"
    assert f2["result"] == "nominal"
    assert f2["disposition"] == "pass"

    # History shows visit to st-fab, st-inspect, st-rework, st-inspect, and terminal
    station_visits = [h["location"] for h in unit.history if h["state"] == "in_station"]
    assert station_visits == ["st-fab", "st-inspect", "st-rework", "st-inspect"]

    # Station scrapped count is 0
    inspect_st = next(s for s in summary.stations if s.id == "st-inspect")
    assert inspect_st.scrapped_count == 0


def test_rework_limit_exceeded_scraps_unit() -> None:
    """When rework fails to restore quality and max_reworks is exceeded, unit is scrapped."""
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
    - id: "st-fab"
      kind: "station"
      operations:
        - id: "op-fab"
          duration: "10s"
          defect_probability: 1.0
          defect_name: "deep_flaw"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-inspect"
      kind: "station"
      operations:
        - id: "op-inspect"
          duration: "5s"
          inspection:
            sensitivity: 1.0
            false_positive_rate: 0.0
            disposition_on_defect: "rework"
            rework_station_id: "st-rework"
            rework_operation_id: "op-attempt-fix"
            max_reworks: 1
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-rework"
      kind: "station"
      operations:
        - id: "op-attempt-fix"
          duration: "5s"
          restores_quality: false  # Fails to restore quality!
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "snk"
      kind: "sink"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
  routes:
    - id: "r-src-fab"
      source_node_id: "src"
      source_port_id: "out"
      target_node_id: "st-fab"
      target_port_id: "in"
    - id: "r-fab-inspect"
      source_node_id: "st-fab"
      source_port_id: "out"
      target_node_id: "st-inspect"
      target_port_id: "in"
    - id: "r-inspect-rework"
      source_node_id: "st-inspect"
      source_port_id: "out"
      target_node_id: "st-rework"
      target_port_id: "in"
    - id: "r-rework-inspect"
      source_node_id: "st-rework"
      source_port_id: "out"
      target_node_id: "st-inspect"
      target_port_id: "in"
    - id: "r-inspect-snk"
      source_node_id: "st-inspect"
      source_port_id: "out"
      target_node_id: "snk"
      target_port_id: "in"
production_plan:
  - id: "unit-1"
    variant: "sedan"
    quantity: 1
process_plans:
  - variant: "sedan"
    steps:
      - operation_id: "op-fab"
        compatible_stations: ["st-fab"]
      - operation_id: "op-inspect"
        compatible_stations: ["st-inspect"]
"""
    summary = run_episode(yaml_content)
    assert summary.status == "completed"

    unit = summary.production_units[0]
    assert unit.quality_state == "deep_flaw"
    assert unit.state == "terminal"

    # Two findings: first disposition rework, second disposition scrap
    assert len(unit.findings) == 2
    assert unit.findings[0]["disposition"] == "rework"
    assert unit.findings[1]["disposition"] == "scrap"

    inspect_st = next(s for s in summary.stations if s.id == "st-inspect")
    assert inspect_st.scrapped_count == 1


def test_checkpoint_equivalence_with_process_plans_and_quality() -> None:
    """Pause mid-episode during rework, save checkpoint, restore, and verify bit-level equivalence."""
    yaml_content = """
schema_version: "1.0"
seed: 999
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
material_flow:
  nodes:
    - id: "src"
      kind: "source"
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-fab"
      kind: "station"
      operations:
        - id: "op-fab"
          duration: "10s"
          defect_probability: 1.0
          defect_name: "flaw"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-inspect"
      kind: "station"
      operations:
        - id: "op-inspect"
          duration: "5s"
          inspection:
            sensitivity: 1.0
            false_positive_rate: 0.0
            disposition_on_defect: "rework"
            rework_station_id: "st-rework"
            rework_operation_id: "op-rework"
            max_reworks: 1
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-rework"
      kind: "station"
      operations:
        - id: "op-rework"
          duration: "8s"
          restores_quality: true
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "snk"
      kind: "sink"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
  routes:
    - id: "r-src-fab"
      source_node_id: "src"
      source_port_id: "out"
      target_node_id: "st-fab"
      target_port_id: "in"
    - id: "r-fab-inspect"
      source_node_id: "st-fab"
      source_port_id: "out"
      target_node_id: "st-inspect"
      target_port_id: "in"
    - id: "r-inspect-rework"
      source_node_id: "st-inspect"
      source_port_id: "out"
      target_node_id: "st-rework"
      target_port_id: "in"
    - id: "r-rework-inspect"
      source_node_id: "st-rework"
      source_port_id: "out"
      target_node_id: "st-inspect"
      target_port_id: "in"
    - id: "r-inspect-snk"
      source_node_id: "st-inspect"
      source_port_id: "out"
      target_node_id: "snk"
      target_port_id: "in"
production_plan:
  - id: "unit-1"
    variant: "sedan"
    quantity: 1
process_plans:
  - variant: "sedan"
    steps:
      - operation_id: "op-fab"
        compatible_stations: ["st-fab"]
      - operation_id: "op-inspect"
        compatible_stations: ["st-inspect"]
"""
    # 1. Uninterrupted reference run
    ref_summary = run_episode(yaml_content)
    assert ref_summary.status == "completed"

    # 2. Segmented run: pause at 18s (during rework operation)
    from industrialsim.application import validate_config
    val_res = validate_config(yaml_content)
    assert val_res.config is not None
    cfg = val_res.config

    engine1 = EpisodeEngine.create(cfg)
    # 18 seconds = 18_000_000_000 ns
    pause_ns = 18_000_000_000
    engine1.run(pause_at_ns=pause_ns)
    cp = engine1.create_checkpoint()

    # Restore in fresh engine and complete
    engine2 = EpisodeEngine.restore(cp)
    restored_summary = engine2.run()

    # 3. Assert exact equivalence
    assert restored_summary.status == "completed"
    assert restored_summary.result_hash == ref_summary.result_hash
    assert restored_summary.simulated_time_ns == ref_summary.simulated_time_ns
    assert restored_summary.events_processed == ref_summary.events_processed

    # Production units equivalence
    assert len(restored_summary.production_units) == len(ref_summary.production_units)
    u_restored = restored_summary.production_units[0]
    u_ref = ref_summary.production_units[0]
    assert u_restored.quality_state == u_ref.quality_state
    assert u_restored.findings == u_ref.findings
    assert u_restored.history == u_ref.history

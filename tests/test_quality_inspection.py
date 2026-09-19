from __future__ import annotations

import pytest

from industrialsim.application import run_episode, validate_config
from industrialsim.config import InspectionConfig


def test_operation_alters_latent_quality_state_and_inspection_detects() -> None:
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
          defect_name: "weld_defect"
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
            disposition_on_defect: "scrap"
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
    assert len(summary.production_units) == 1

    unit = summary.production_units[0]
    # Unit was scrapped due to detected defect: latent quality_state is preserved
    assert unit.quality_state == "weld_defect"
    assert unit.state == "terminal"
    assert unit.findings[0]["disposition"] == "scrap"

    # Station summary reflects the scrap
    inspect_st = next(s for s in summary.stations if s.id == "st-inspect")
    assert inspect_st.scrapped_count == 1


def test_undetected_defect_passes_inspection_when_sensitivity_zero() -> None:
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
          defect_name: "hidden_crack"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "st-inspect"
      kind: "station"
      operations:
        - id: "op-inspect"
          duration: "5s"
          inspection:
            sensitivity: 0.0  # Cannot detect the defect!
            false_positive_rate: 0.0
            disposition_on_defect: "scrap"
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
    # Unit reached sink as terminal, but its latent quality state remains defective
    assert unit.location == "terminal"
    assert unit.quality_state == "hidden_crack"

    # Station scrapped_count is 0 because defect went undetected
    inspect_st = next(s for s in summary.stations if s.id == "st-inspect")
    assert inspect_st.scrapped_count == 0


def test_false_positive_causes_scrap_on_nominal_unit() -> None:
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
    - id: "st-inspect"
      kind: "station"
      operations:
        - id: "op-inspect"
          duration: "5s"
          inspection:
            sensitivity: 1.0
            false_positive_rate: 1.0  # Always triggers false positive
            disposition_on_defect: "scrap"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
      output_ports: [{id: "out", port_type: "body", direction: "output"}]
    - id: "snk"
      kind: "sink"
      input_ports: [{id: "in", port_type: "body", direction: "input"}]
  routes:
    - id: "r-src-inspect"
      source_node_id: "src"
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
      - operation_id: "op-inspect"
        compatible_stations: ["st-inspect"]
"""
    summary = run_episode(yaml_content)
    assert summary.status == "completed"

    unit = summary.production_units[0]
    # Latent quality_state is still nominal, but unit was terminated due to false positive finding
    assert unit.quality_state == "nominal"
    assert unit.state == "terminal"
    assert unit.findings[0]["disposition"] == "scrap"

    inspect_st = next(s for s in summary.stations if s.id == "st-inspect")
    assert inspect_st.scrapped_count == 1

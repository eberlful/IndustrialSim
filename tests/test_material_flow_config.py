import pytest
from industrialsim.application import validate_config


VALID_MATERIAL_FLOW_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

plant:
  id: "plant-main"
  name: "Main Assembly Plant"
  areas:
    - id: "area-body"
      name: "Body Shop"
      halls:
        - id: "hall-b1"
          name: "Body Welding Hall"
    - id: "area-assembly"
      name: "Final Assembly"
      halls:
        - id: "hall-a1"
          name: "Assembly Line 1"

material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      hall_id: "hall-b1"
      output_ports:
        - id: "out-1"
          port_type: "vehicle_body"
          direction: "output"
    - id: "st-1"
      kind: "station"
      hall_id: "hall-b1"
      operations:
        - id: "op-weld"
          duration: "5s"
      input_ports:
        - id: "in-1"
          port_type: "vehicle_body"
          direction: "input"
      output_ports:
        - id: "out-1"
          port_type: "vehicle_body"
          direction: "output"
    - id: "buf-1"
      kind: "buffer"
      capacity: 1
      hall_id: "hall-a1"
      input_ports:
        - id: "in-1"
          port_type: "vehicle_body"
          direction: "input"
      output_ports:
        - id: "out-1"
          port_type: "vehicle_body"
          direction: "output"
    - id: "st-2"
      kind: "station"
      hall_id: "hall-a1"
      operations:
        - id: "op-assemble"
          duration: "10s"
      input_ports:
        - id: "in-1"
          port_type: "vehicle_body"
          direction: "input"
      output_ports:
        - id: "out-1"
          port_type: "vehicle_body"
          direction: "output"
    - id: "snk-1"
      kind: "sink"
      hall_id: "hall-a1"
      input_ports:
        - id: "in-1"
          port_type: "vehicle_body"
          direction: "input"
  routes:
    - id: "r1"
      source_node_id: "src-1"
      source_port_id: "out-1"
      target_node_id: "st-1"
      target_port_id: "in-1"
      transit_time: "1s"
    - id: "r2"
      source_node_id: "st-1"
      source_port_id: "out-1"
      target_node_id: "buf-1"
      target_port_id: "in-1"
    - id: "r3"
      source_node_id: "buf-1"
      source_port_id: "out-1"
      target_node_id: "st-2"
      target_port_id: "in-1"
    - id: "r4"
      source_node_id: "st-2"
      source_port_id: "out-1"
      target_node_id: "snk-1"
      target_port_id: "in-1"

production_units:
  - id: "unit-001"
    variant: "sedan"
    release_time: "0s"
"""


def test_validate_material_flow_config_valid() -> None:
    result = validate_config(VALID_MATERIAL_FLOW_YAML)
    assert result.is_valid is True
    assert result.errors == []
    assert result.config is not None
    assert result.config.plant is not None
    assert result.config.plant.id == "plant-main"
    assert result.config.material_flow is not None
    assert len(result.config.material_flow.nodes) == 5
    assert len(result.config.material_flow.routes) == 4


def test_validate_material_flow_incompatible_ports() -> None:
    # Change r1 target_port_id or st-1 port_type to an incompatible type
    incompatible_yaml = VALID_MATERIAL_FLOW_YAML.replace(
        'port_type: "vehicle_body"\n          direction: "input"',
        'port_type: "chassis"\n          direction: "input"',
        1,
    )
    result = validate_config(incompatible_yaml)
    assert result.is_valid is False
    assert any("incompatible port type" in err.lower() for err in result.errors)


def test_validate_material_flow_duplicate_node_ids() -> None:
    dup_yaml = VALID_MATERIAL_FLOW_YAML.replace('id: "st-2"', 'id: "st-1"')
    result = validate_config(dup_yaml)
    assert result.is_valid is False
    assert any("duplicate" in err.lower() for err in result.errors)


def test_validate_material_flow_unreachable_sink() -> None:
    # Break route r4 so snk-1 cannot be reached
    broken_yaml = VALID_MATERIAL_FLOW_YAML.replace('target_node_id: "snk-1"', 'target_node_id: "st-1"')
    result = validate_config(broken_yaml)
    assert result.is_valid is False
    assert any("unreachable" in err.lower() for err in result.errors)

from __future__ import annotations

import pytest

from industrialsim.application import validate_config
from industrialsim.config import RouteConfig, VehicleConfig, VehiclePoolConfig


BASE_CONFIG_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      output_ports:
        - id: "out"
          port_type: "body"
          direction: "output"
    - id: "st-1"
      kind: "station"
      operations:
        - id: "op-1"
          duration: "10s"
      input_ports:
        - id: "in"
          port_type: "body"
          direction: "input"
      output_ports:
        - id: "out"
          port_type: "body"
          direction: "output"
    - id: "snk-1"
      kind: "sink"
      input_ports:
        - id: "in"
          port_type: "body"
          direction: "input"
  routes:
    - id: "r-src-st1"
      source_node_id: "src-1"
      source_port_id: "out"
      target_node_id: "st-1"
      target_port_id: "in"
      transit_time: "5s"
      capacity: 2
    - id: "r-st1-snk"
      source_node_id: "st-1"
      source_port_id: "out"
      target_node_id: "snk-1"
      target_port_id: "in"
      transit_time: "5s"
      capacity: 1
production_units:
  - id: "u-1"
    variant: "sedan"
    source_id: "src-1"
vehicle_pools:
  - id: "agv_pool"
    name: "AGV Fleet"
    capabilities: ["standard", "agv"]
vehicles:
  - id: "v-1"
    pool_id: "agv_pool"
    capabilities: ["agv"]
    initial_location: "src-1"
  - id: "v-2"
    capabilities: ["forklift"]
    initial_location: "st-1"
"""


def test_vehicle_and_pool_config_valid() -> None:
    res = validate_config(BASE_CONFIG_YAML)
    assert res.is_valid, f"Expected valid config, got errors: {res.errors}"
    cfg = res.config
    assert cfg is not None
    assert len(cfg.vehicles) == 2
    assert len(cfg.vehicle_pools) == 1
    assert cfg.vehicles[0].id == "v-1"
    assert cfg.vehicles[0].pool_id == "agv_pool"
    assert cfg.vehicles[0].initial_location == "src-1"
    assert cfg.material_flow is not None
    assert cfg.material_flow.routes[0].capacity == 2
    assert cfg.material_flow.routes[1].capacity == 1


def test_vehicle_config_rejects_duplicate_vehicle_ids() -> None:
    yaml_str = BASE_CONFIG_YAML.replace('id: "v-2"', 'id: "v-1"')
    res = validate_config(yaml_str)
    assert not res.is_valid
    assert any("Duplicate vehicle IDs found" in err for err in res.errors)


def test_vehicle_config_rejects_unknown_initial_location() -> None:
    yaml_str = BASE_CONFIG_YAML.replace('initial_location: "st-1"', 'initial_location: "non-existent-node"')
    res = validate_config(yaml_str)
    assert not res.is_valid
    assert any("references unknown initial_location 'non-existent-node'" in err for err in res.errors)


def test_vehicle_config_rejects_unknown_pool_id() -> None:
    yaml_str = BASE_CONFIG_YAML.replace('pool_id: "agv_pool"', 'pool_id: "unknown_pool"')
    res = validate_config(yaml_str)
    assert not res.is_valid
    assert any("references unknown vehicle pool 'unknown_pool'" in err for err in res.errors)


def test_route_config_rejects_invalid_capacity() -> None:
    yaml_str = BASE_CONFIG_YAML.replace("capacity: 2", "capacity: 0")
    res = validate_config(yaml_str)
    assert not res.is_valid
    assert any("capacity must be >= 1" in err for err in res.errors)

from __future__ import annotations

import pytest
from industrialsim.config import (
    DeadlockConfig,
    EndConditionConfig,
    SimulationConfig,
)
from industrialsim.application import validate_config


def test_deadlock_config_defaults_and_duration_parsing() -> None:
    cfg = DeadlockConfig(max_interval_without_progress="45s")
    assert cfg.enabled is True
    assert cfg.max_interval_without_progress == "45s"
    assert cfg.max_interval_without_progress_ns == 45_000_000_000


def test_deadlock_config_numeric_duration() -> None:
    cfg = DeadlockConfig(max_interval_without_progress=10_000_000)
    assert cfg.max_interval_without_progress_ns == 10_000_000


def test_deadlock_config_in_simulation_config_yaml() -> None:
    yaml_content = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0s
  end_condition:
    type: "all_units_terminal"
production_units:
  - id: "u-01"
    variant: "sedan"
stations:
  - id: "st-1"
    operations:
      - id: "op-1"
        duration: "10s"
deadlock:
  enabled: true
  max_interval_without_progress: "30s"
"""
    val = validate_config(yaml_content)
    assert val.is_valid, val.errors
    assert val.config is not None
    assert val.config.deadlock is not None
    assert val.config.deadlock.enabled is True
    assert val.config.deadlock.max_interval_without_progress_ns == 30_000_000_000


def test_strict_validation_rejects_unknown_fields_per_adr0012() -> None:
    # ADR-0012 strict declarative configuration requires unknown fields to fail validation
    yaml_content = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0s
  end_condition:
    type: "all_units_terminal"
production_units:
  - id: "u-01"
    variant: "sedan"
stations:
  - id: "st-1"
    operations:
      - id: "op-1"
        duration: "10s"
deadlock_detection:
  enabled: false
"""
    val = validate_config(yaml_content)
    assert not val.is_valid
    assert any("Extra inputs are not permitted" in err for err in val.errors)

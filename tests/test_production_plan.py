from __future__ import annotations

import pytest

from industrialsim.application import run_episode, validate_config
from industrialsim.config import ProductionPlanEntryConfig, SimulationConfig


def test_production_plan_config_validation() -> None:
    yaml_content = """
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
  - id: "order-sedan"
    variant: "sedan"
    quantity: 2
    release_time: "5s"
    due_date: "1h"
  - id: "order-suv"
    variant: "suv"
    quantity: 1
    release_time: "10s"
"""
    val = validate_config(yaml_content)
    assert val.is_valid, f"Validation failed: {val.errors}"
    assert val.config is not None
    assert len(val.config.production_plan) == 2
    assert val.config.production_plan[0].quantity == 2
    assert val.config.production_plan[0].release_time_ns == 5_000_000_000
    assert val.config.production_plan[0].due_date_ns == 3_600_000_000_000
    assert val.config.production_plan[1].quantity == 1
    assert val.config.production_plan[1].release_time_ns == 10_000_000_000


def test_production_plan_rejects_invalid_quantity() -> None:
    yaml_content = """
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
    quantity: 0
"""
    val = validate_config(yaml_content)
    assert not val.is_valid
    assert any("quantity" in err for err in val.errors)


def test_production_plan_materializes_deterministic_identities() -> None:
    yaml_content = """
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
  - id: "batch-A"
    variant: "sedan"
    quantity: 2
    release_time: "1s"
    due_date: "100s"
  - variant: "suv"
    quantity: 2
    release_time: "2s"
"""
    summary1 = run_episode(yaml_content)
    summary2 = run_episode(yaml_content)

    assert summary1.status == "completed"
    assert summary2.status == "completed"
    assert summary1.result_hash == summary2.result_hash

    # Units materialized: 2 sedan + 2 suv = 4 units
    assert len(summary1.production_units) == 4
    unit_ids = [u.id for u in summary1.production_units]
    assert unit_ids == [
        "batch-A-1",
        "batch-A-2",
        "suv-2-1",
        "suv-2-2",
    ]
    variants = [u.variant for u in summary1.production_units]
    assert variants == ["sedan", "sedan", "suv", "suv"]

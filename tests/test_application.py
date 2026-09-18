import pytest
from industrialsim.application import validate_config, run_episode


MINIMAL_VALID_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"
production_units:
  - id: "unit-001"
    variant: "sedan"
    release_time: "0s"
stations:
  - id: "station-001"
    operations:
      - id: "op-assembly"
        duration: "10s"
"""

YAML_WITH_UNKNOWN_FIELD = """
schema_version: "1.0"
seed: 42
unknown_root_field: "invalid"
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"
production_units:
  - id: "unit-001"
    variant: "sedan"
stations:
  - id: "station-001"
    operations:
      - id: "op-assembly"
        duration: "10s"
"""

YAML_WITH_UNKNOWN_NESTED_FIELD = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"
    rogue_option: true
production_units:
  - id: "unit-001"
    variant: "sedan"
stations:
  - id: "station-001"
    operations:
      - id: "op-assembly"
        duration: "10s"
"""


def test_validate_valid_config() -> None:
    result = validate_config(MINIMAL_VALID_YAML)
    assert result.is_valid is True
    assert result.errors == []
    assert result.config is not None
    assert result.config.production_units[0].id == "unit-001"
    assert result.config.stations[0].operations[0].duration_ns == 10_000_000_000


def test_validate_rejects_unknown_root_fields() -> None:
    result = validate_config(YAML_WITH_UNKNOWN_FIELD)
    assert result.is_valid is False
    assert len(result.errors) > 0
    assert any("unknown_root_field" in err or "extra" in err.lower() for err in result.errors)


def test_validate_rejects_unknown_nested_fields() -> None:
    result = validate_config(YAML_WITH_UNKNOWN_NESTED_FIELD)
    assert result.is_valid is False
    assert len(result.errors) > 0
    assert any("rogue_option" in err or "extra" in err.lower() for err in result.errors)


def test_run_minimal_episode_to_terminal_state() -> None:
    summary = run_episode(MINIMAL_VALID_YAML)
    assert summary.status == "completed"
    assert summary.simulated_time_ns == 10_000_000_000
    assert summary.events_processed > 0

    # Production Unit reached terminal state
    assert len(summary.production_units) == 1
    unit = summary.production_units[0]
    assert unit.id == "unit-001"
    assert unit.variant == "sedan"
    assert unit.state == "terminal"
    assert len(unit.history) >= 3

    # Station summary
    assert len(summary.stations) == 1
    station = summary.stations[0]
    assert station.id == "station-001"
    assert station.operations_completed == 1
    assert station.total_busy_time_ns == 10_000_000_000

    # Result hash is deterministic and present
    assert isinstance(summary.result_hash, str)
    assert len(summary.result_hash) == 64

    # Internals are not exposed on summary
    assert not hasattr(summary, "kernel")
    assert not hasattr(summary, "_queue")


def test_run_episode_determinism() -> None:
    summary1 = run_episode(MINIMAL_VALID_YAML)
    summary2 = run_episode(MINIMAL_VALID_YAML)

    assert summary1.result_hash == summary2.result_hash
    assert summary1.simulated_time_ns == summary2.simulated_time_ns
    assert summary1.events_processed == summary2.events_processed
    assert summary1.to_dict() == summary2.to_dict()


def test_run_episode_with_offset_start_time() -> None:
    yaml_config = """
schema_version: "1.0"
seed: 123
episode:
  start_time: "5s"
  end_condition:
    type: "all_units_terminal"
production_units:
  - id: "unit-002"
    variant: "suv"
    release_time: "5s"
stations:
  - id: "station-001"
    operations:
      - id: "op-assembly"
        duration: "15s"
"""
    summary = run_episode(yaml_config)
    assert summary.status == "completed"
    # start_time 5s + duration 15s = 20s
    assert summary.simulated_time_ns == 20_000_000_000
    assert summary.production_units[0].id == "unit-002"
    assert summary.production_units[0].state == "terminal"


def test_run_invalid_config_raises_error() -> None:
    with pytest.raises(ValueError, match="Invalid configuration"):
        run_episode(YAML_WITH_UNKNOWN_FIELD)


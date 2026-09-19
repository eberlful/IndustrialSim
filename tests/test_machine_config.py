import pytest
from pydantic import ValidationError
from industrialsim.application import validate_config
from industrialsim.config import (
    DegradationPolicyConfig,
    FailurePolicyConfig,
    MachineConfig,
    MachineModeConfig,
    MaintenancePolicyConfig,
    PlannedDisruptionConfig,
    SimulationConfig,
    WorkerRequirementConfig,
)


def test_machine_config_defaults() -> None:
    m = MachineConfig(id="m1")
    assert m.id == "m1"
    assert m.initial_health == 1.0
    assert m.operating_mode == "nominal"
    assert m.modes == {}
    assert m.degradation is None
    assert m.maintenance is None
    assert m.failure is None
    assert m.planned_disruptions == []
    assert m.physical_state == {}


def test_machine_config_invalid_health() -> None:
    with pytest.raises(ValidationError):
        MachineConfig(id="m1", initial_health=1.5)

    with pytest.raises(ValidationError):
        MachineConfig(id="m1", initial_health=-0.1)


def test_machine_config_with_modes_and_degradation() -> None:
    m = MachineConfig(
        id="m1",
        initial_health=0.9,
        operating_mode="fast",
        modes={
            "nominal": MachineModeConfig(name="nominal", degradation_multiplier=1.0, cycle_time_multiplier=1.0),
            "fast": MachineModeConfig(name="fast", degradation_multiplier=2.0, cycle_time_multiplier=0.8),
        },
        degradation=DegradationPolicyConfig(
            use_rate_per_s=0.01,
            idle_rate_per_s=0.001,
            cycle_time_factor=0.5,
            defect_probability_factor=0.2,
        ),
        physical_state={"temperature": 25.0, "vibration": 0.05},
    )
    assert m.initial_health == 0.9
    assert m.operating_mode == "fast"
    assert "fast" in m.modes
    assert m.modes["fast"].degradation_multiplier == 2.0
    assert m.degradation is not None
    assert m.degradation.use_rate_per_s == 0.01
    assert m.physical_state["temperature"] == 25.0


def test_machine_config_maintenance_and_failure_policies() -> None:
    m = MachineConfig(
        id="m1",
        maintenance=MaintenancePolicyConfig(
            trigger="condition_threshold",
            health_threshold=0.4,
            duration="30s",
            restored_health=0.85,
            required_workers=[WorkerRequirementConfig(qualification="maintenance", count=1)],
        ),
        failure=FailurePolicyConfig(
            hazard_rate_per_s=0.002,
            health_hazard_factor=3.0,
            repair_duration="45s",
            repaired_health=0.80,
            required_workers=[WorkerRequirementConfig(qualification="maintenance", count=1)],
        ),
        planned_disruptions=[
            PlannedDisruptionConfig(
                start_time="100s",
                duration="20s",
                repaired_health=0.9,
                required_workers=[WorkerRequirementConfig(qualification="maintenance", count=1)],
            )
        ],
    )
    assert m.maintenance is not None
    assert m.maintenance.duration_ns == 30_000_000_000
    assert m.maintenance.restored_health == 0.85
    assert m.failure is not None
    assert m.failure.repair_duration_ns == 45_000_000_000
    assert m.failure.repaired_health == 0.80
    assert len(m.planned_disruptions) == 1
    assert m.planned_disruptions[0].start_time_ns == 100_000_000_000
    assert m.planned_disruptions[0].duration_ns == 20_000_000_000


def test_machine_config_validation_unknown_qualification() -> None:
    yaml_content = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
workers:
  - id: "w1"
    qualifications: ["operator"]
machines:
  - id: "m1"
    maintenance:
      duration: "10s"
      restored_health: 0.9
      required_workers:
        - qualification: "nonexistent_qualification"
stations:
  - id: "st1"
    operations:
      - id: "op1"
        duration: "5s"
        required_machines: ["m1"]
production_units:
  - id: "u1"
    variant: "sedan"
"""
    res = validate_config(yaml_content)
    assert not res.is_valid
    assert any("unknown qualification" in err for err in res.errors)


def test_machine_config_inspection_and_mttr() -> None:
    yaml_content = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
machines:
  - id: "m1"
    inspection:
      interval: "1h"
      duration: "5m"
      restored_health: 0.95
    failure:
      mttf: "2h"
      mttr: "15m"
      repaired_health: 0.85
stations:
  - id: "st1"
    operations:
      - id: "op1"
        duration: "10s"
        required_machines: ["m1"]
production_units:
  - id: "u1"
    variant: "sedan"
"""
    res = validate_config(yaml_content)
    assert res.is_valid
    assert res.config is not None
    m = res.config.machines[0]
    assert m.inspection is not None
    assert m.inspection.interval_ns == 3600 * 1_000_000_000
    assert m.inspection.duration_ns == 300 * 1_000_000_000
    assert m.inspection.restored_health == 0.95
    assert m.failure is not None
    assert m.failure.mttr_ns == 900 * 1_000_000_000

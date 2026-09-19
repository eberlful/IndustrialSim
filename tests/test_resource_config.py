import pytest
from industrialsim.application import validate_config


VALID_RESOURCE_CONFIG_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

machines:
  - id: "mach-welder-1"
    name: "Robot Welder 1"
    capacity: 1
    shifts:
      - id: "shift-all-day"
        start_time: "0s"
        end_time: "24h"
    breaks:
      - start_time: "4h"
        duration: "30m"
  - id: "mach-press-multi"
    capacity: 2

workers:
  - id: "worker-alice"
    kind: "individual"
    qualifications: ["welding", "inspection"]
    shifts:
      - id: "shift-morning"
        start_time: "0s"
        end_time: "8h"
        handover_rule: "handover"
        breaks:
          - start_time: "4h"
            end_time: "4h30m"
  - id: "pool-welders"
    kind: "pool"
    capacity: 3
    qualifications: ["welding"]
    shifts:
      - id: "shift-full"
        start_time: "0s"
        end_time: "16h"

material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "vehicle"
          direction: "output"
    - id: "st-1"
      kind: "station"
      operations:
        - id: "op-weld"
          duration: "5s"
          required_machines: ["mach-welder-1"]
          required_workers:
            - qualification: "welding"
              count: 1
          interruption_policy: "resume"
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
    - id: "r-st1-snk"
      source_node_id: "st-1"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"

production_units:
  - id: "unit-1"
    variant: "sedan"
    release_time: "0s"
"""


def test_valid_resource_config_loads_successfully() -> None:
    result = validate_config(VALID_RESOURCE_CONFIG_YAML)
    assert result.is_valid, f"Validation failed with errors: {result.errors}"
    assert result.config is not None
    assert len(result.config.machines) == 2
    assert len(result.config.workers) == 2
    mach1 = result.config.machines[0]
    assert mach1.id == "mach-welder-1"
    assert mach1.capacity == 1
    assert len(mach1.shifts) == 1
    assert mach1.shifts[0].start_time_ns == 0
    assert mach1.shifts[0].end_time_ns == 24 * 3600 * 1_000_000_000
    assert len(mach1.breaks) == 1
    assert mach1.breaks[0].duration_ns == 30 * 60 * 1_000_000_000

    w_indiv = result.config.workers[0]
    assert w_indiv.id == "worker-alice"
    assert w_indiv.kind == "individual"
    assert w_indiv.capacity == 1
    assert "welding" in w_indiv.qualifications
    assert w_indiv.shifts[0].handover_rule == "handover"

    w_pool = result.config.workers[1]
    assert w_pool.id == "pool-welders"
    assert w_pool.kind == "pool"
    assert w_pool.capacity == 3


def test_reject_duplicate_machine_or_worker_ids() -> None:
    # Duplicate machine
    yaml_dup_mach = VALID_RESOURCE_CONFIG_YAML.replace(
        '  - id: "mach-press-multi"',
        '  - id: "mach-welder-1"',
    )
    res = validate_config(yaml_dup_mach)
    assert not res.is_valid
    assert any("Duplicate machine ID" in err for err in res.errors)

    # Duplicate worker
    yaml_dup_worker = VALID_RESOURCE_CONFIG_YAML.replace(
        '  - id: "pool-welders"',
        '  - id: "worker-alice"',
    )
    res = validate_config(yaml_dup_worker)
    assert not res.is_valid
    assert any("Duplicate worker ID" in err for err in res.errors)


def test_reject_invalid_machine_capacity() -> None:
    yaml_bad_cap = VALID_RESOURCE_CONFIG_YAML.replace(
        '    capacity: 1',
        '    capacity: 0',
    )
    res = validate_config(yaml_bad_cap)
    assert not res.is_valid
    assert any("capacity" in err.lower() for err in res.errors)


def test_reject_invalid_shift_and_break_times() -> None:
    # Shift start >= end
    yaml_bad_shift = VALID_RESOURCE_CONFIG_YAML.replace(
        '        start_time: "0s"\n        end_time: "24h"',
        '        start_time: "10s"\n        end_time: "5s"',
    )
    res = validate_config(yaml_bad_shift)
    assert not res.is_valid
    assert any("shift" in err.lower() and "time" in err.lower() for err in res.errors)


def test_reject_operation_referencing_unknown_machine() -> None:
    yaml_bad_op = VALID_RESOURCE_CONFIG_YAML.replace(
        'required_machines: ["mach-welder-1"]',
        'required_machines: ["unknown-mach-99"]',
    )
    res = validate_config(yaml_bad_op)
    assert not res.is_valid
    assert any("unknown-mach-99" in err for err in res.errors)


def test_reject_operation_referencing_unknown_qualification() -> None:
    yaml_bad_qual = VALID_RESOURCE_CONFIG_YAML.replace(
        'qualification: "welding"',
        'qualification: "unknown-qual"',
    )
    res = validate_config(yaml_bad_qual)
    assert not res.is_valid
    assert any("unknown-qual" in err for err in res.errors)


def test_reject_invalid_interruption_policy() -> None:
    yaml_bad_policy = VALID_RESOURCE_CONFIG_YAML.replace(
        'interruption_policy: "resume"',
        'interruption_policy: "explode"',
    )
    res = validate_config(yaml_bad_policy)
    assert not res.is_valid

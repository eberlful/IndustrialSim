from pathlib import Path
from typing import Any
import pytest

from industrialsim.application import (
    create_checkpoint,
    inspect_checkpoint,
    resume_episode,
    run_episode,
    save_checkpoint,
)
from industrialsim.checkpoint import (
    IncompatibleCheckpointError,
    InvalidCheckpointError,
)

MINIMAL_YAML = """
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

BLOCKING_SCENARIO_YAML = """
schema_version: "1.0"
seed: 100
episode:
  start_time: "0s"
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
        - id: "weld"
          duration: "2s"
      input_ports:
        - id: "in"
          port_type: "body"
          direction: "input"
      output_ports:
        - id: "out"
          port_type: "body"
          direction: "output"
    - id: "buf-1"
      kind: "buffer"
      capacity: 1
      input_ports:
        - id: "in"
          port_type: "body"
          direction: "input"
      output_ports:
        - id: "out"
          port_type: "body"
          direction: "output"
    - id: "st-2"
      kind: "station"
      operations:
        - id: "paint"
          duration: "8s"
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
    - id: "r-st1-buf"
      source_node_id: "st-1"
      source_port_id: "out"
      target_node_id: "buf-1"
      target_port_id: "in"
    - id: "r-buf-st2"
      source_node_id: "buf-1"
      source_port_id: "out"
      target_node_id: "st-2"
      target_port_id: "in"
    - id: "r-st2-snk"
      source_node_id: "st-2"
      source_port_id: "out"
      target_node_id: "snk-1"
      target_port_id: "in"
production_units:
  - id: "u-01"
    variant: "sedan"
    source_id: "src-1"
    release_time: "0s"
  - id: "u-02"
    variant: "suv"
    source_id: "src-1"
    release_time: "1s"
  - id: "u-03"
    variant: "sedan"
    source_id: "src-1"
    release_time: "2s"
"""


def test_minimal_episode_uninterrupted_vs_resumed_equivalence(tmp_path: Path) -> None:
    # 1. Uninterrupted run
    uninterrupted_summary = run_episode(MINIMAL_YAML)
    assert uninterrupted_summary.status == "completed"

    # 2. Checkpoint at 5s (halfway through the 10s assembly operation)
    cp = create_checkpoint(MINIMAL_YAML, at_time_ns=5_000_000_000)
    assert cp.simulated_time_ns == 5_000_000_000

    cp_file = tmp_path / "minimal_checkpoint.json"
    save_checkpoint(cp, cp_file)

    # 3. Resume from checkpoint in fresh state
    resumed_summary = resume_episode(cp_file)

    # 4. Assert exact bit-for-bit equivalence
    assert resumed_summary.status == uninterrupted_summary.status
    assert resumed_summary.simulated_time_ns == uninterrupted_summary.simulated_time_ns
    assert resumed_summary.events_processed == uninterrupted_summary.events_processed
    assert resumed_summary.result_hash == uninterrupted_summary.result_hash
    assert resumed_summary.to_dict() == uninterrupted_summary.to_dict()


def test_material_flow_blocking_uninterrupted_vs_resumed_equivalence(tmp_path: Path) -> None:
    # 1. Uninterrupted run
    uninterrupted_summary = run_episode(BLOCKING_SCENARIO_YAML)
    assert uninterrupted_summary.status == "completed"

    # 2. Checkpoint at 7s (st-1 is blocked, buf-1 has u-02, st-2 is processing u-01)
    cp = create_checkpoint(BLOCKING_SCENARIO_YAML, at_time_ns=7_000_000_000)
    assert cp.simulated_time_ns == 7_000_000_000

    cp_file = tmp_path / "blocking_checkpoint.json"
    save_checkpoint(cp, cp_file)

    # 3. Resume from checkpoint
    resumed_summary = resume_episode(cp_file)

    # 4. Assert exact equivalence across all domain elements, metrics, and result hashes
    assert resumed_summary.status == uninterrupted_summary.status
    assert resumed_summary.simulated_time_ns == uninterrupted_summary.simulated_time_ns
    assert resumed_summary.events_processed == uninterrupted_summary.events_processed
    assert resumed_summary.result_hash == uninterrupted_summary.result_hash
    assert resumed_summary.to_dict() == uninterrupted_summary.to_dict()


def test_checkpoint_compatibility_diagnostics(tmp_path: Path) -> None:
    cp = create_checkpoint(MINIMAL_YAML, at_time_ns=5_000_000_000)

    # Incompatible schema version
    cp_bad_schema = create_checkpoint(MINIMAL_YAML, at_time_ns=5_000_000_000)
    cp_bad_schema.schema_version = "99.0"
    cp_bad_schema_file = tmp_path / "bad_schema.json"
    save_checkpoint(cp_bad_schema, cp_bad_schema_file)

    with pytest.raises(IncompatibleCheckpointError, match=r"Incompatible schema version: expected '1\.0', got '99\.0'"):
        resume_episode(cp_bad_schema_file)

    # Incompatible kernel version
    cp_bad_kernel = create_checkpoint(MINIMAL_YAML, at_time_ns=5_000_000_000)
    cp_bad_kernel.kernel_version = "2.0"
    cp_bad_kernel_file = tmp_path / "bad_kernel.json"
    save_checkpoint(cp_bad_kernel, cp_bad_kernel_file)

    with pytest.raises(IncompatibleCheckpointError, match=r"Incompatible kernel version: expected '1\.0', got '2\.0'"):
        resume_episode(cp_bad_kernel_file)

    # Incompatible model hash when providing a config with different station operations
    different_model_yaml = MINIMAL_YAML.replace('duration: "10s"', 'duration: "20s"')
    cp_file = tmp_path / "valid_cp.json"
    save_checkpoint(cp, cp_file)

    with pytest.raises(IncompatibleCheckpointError, match=r"(?i)model hash mismatch"):
        resume_episode(cp_file, config_source=different_model_yaml)

    # Incompatible config hash when providing a config with same model but different seed
    different_config_yaml = MINIMAL_YAML.replace("seed: 42", "seed: 99")
    with pytest.raises(IncompatibleCheckpointError, match=r"(?i)configuration hash mismatch"):
        resume_episode(cp_file, config_source=different_config_yaml)

    # Incompatible plugin metadata
    cp_bad_plugin = create_checkpoint(MINIMAL_YAML, at_time_ns=5_000_000_000)
    cp_bad_plugin.plugin_metadata = {"custom_welder": "2.1.0"}
    cp_bad_plugin_file = tmp_path / "bad_plugin.json"
    save_checkpoint(cp_bad_plugin, cp_bad_plugin_file)

    with pytest.raises(IncompatibleCheckpointError, match=r"(?i)plugin"):
        resume_episode(cp_bad_plugin_file)


def test_continue_checkpoint_intermediate_and_completion(tmp_path: Path) -> None:
    from industrialsim.application import continue_checkpoint

    # Checkpoint at 3s
    cp1 = create_checkpoint(MINIMAL_YAML, at_time_ns=3_000_000_000)
    assert cp1.simulated_time_ns == 3_000_000_000

    # Continue until intermediate time 7s
    intermediate_summary = continue_checkpoint(cp1, until_time_ns=7_000_000_000)
    assert intermediate_summary.simulated_time_ns == 7_000_000_000
    assert intermediate_summary.status == "incomplete"

    # Continue from cp1 all the way to completion
    final_summary = continue_checkpoint(cp1)
    assert final_summary.status == "completed"
    assert final_summary.simulated_time_ns == 10_000_000_000


def test_observable_interleaved_event_order_equivalence(tmp_path: Path) -> None:
    # 1. Uninterrupted run
    uninterrupted_summary = run_episode(BLOCKING_SCENARIO_YAML)

    # 2. Checkpoint mid-run at 6s
    cp = create_checkpoint(BLOCKING_SCENARIO_YAML, at_time_ns=6_000_000_000)
    cp_file = tmp_path / "interleaved_cp.json"
    save_checkpoint(cp, cp_file)

    # 3. Resume from checkpoint
    resumed_summary = resume_episode(cp_file)

    # 4. Extract interleaved observable event stream across all units
    def extract_interleaved_events(summary: Any) -> list[tuple[int, str, str, str]]:
        events = []
        for u in summary.production_units:
            for h in u.history:
                events.append((h["time_ns"], u.id, h["state"], h["location"]))
        events.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
        return events

    uninterrupted_events = extract_interleaved_events(uninterrupted_summary)
    resumed_events = extract_interleaved_events(resumed_summary)

    assert len(uninterrupted_events) > 0
    assert resumed_events == uninterrupted_events

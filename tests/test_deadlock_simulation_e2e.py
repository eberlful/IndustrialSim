from __future__ import annotations

import io
import json
from pathlib import Path
import pytest
from industrialsim.application import run_episode, inspect
from industrialsim.cli import main as cli_main


BUFFER_CYCLE_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0s
  end_condition:
    type: "all_units_terminal"
deadlock:
  enabled: true
  max_interval_without_progress: "5s"
process_plans:
  - variant: "plan-A"
    steps:
      - id: "s1"
        operation_id: "op-A"
        compatible_stations: ["st-A"]
      - id: "s2"
        operation_id: "op-B"
        compatible_stations: ["st-B"]
  - variant: "plan-B"
    steps:
      - id: "s1"
        operation_id: "op-B"
        compatible_stations: ["st-B"]
      - id: "s2"
        operation_id: "op-A"
        compatible_stations: ["st-A"]
material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "st-A"
      kind: "station"
      output_capacity: 0
      operations:
        - id: "op-A"
          duration: "1s"
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "st-B"
      kind: "station"
      output_capacity: 0
      operations:
        - id: "op-B"
          duration: "1s"
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "buf-A"
      kind: "buffer"
      capacity: 1
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "buf-B"
      kind: "buffer"
      capacity: 1
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "sink-1"
      kind: "sink"
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
  routes:
    - id: "r-src-stA"
      source_node_id: "src-1"
      source_port_id: "out"
      target_node_id: "st-A"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-src-stB"
      source_node_id: "src-1"
      source_port_id: "out"
      target_node_id: "st-B"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-stA-bufB"
      source_node_id: "st-A"
      source_port_id: "out"
      target_node_id: "buf-B"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-bufB-stB"
      source_node_id: "buf-B"
      source_port_id: "out"
      target_node_id: "st-B"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-stB-bufA"
      source_node_id: "st-B"
      source_port_id: "out"
      target_node_id: "buf-A"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-bufA-stA"
      source_node_id: "buf-A"
      source_port_id: "out"
      target_node_id: "st-A"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-stA-sink"
      source_node_id: "st-A"
      source_port_id: "out"
      target_node_id: "sink-1"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-stB-sink"
      source_node_id: "st-B"
      source_port_id: "out"
      target_node_id: "sink-1"
      target_port_id: "in"
      transit_time: "1s"
production_units:
  - id: "u-1"
    variant: "plan-A"
    release_time: "0s"
  - id: "u-2"
    variant: "plan-B"
    release_time: "0s"
  - id: "u-3"
    variant: "plan-A"
    release_time: "0s"
  - id: "u-4"
    variant: "plan-B"
    release_time: "0s"
"""


def test_e2e_buffer_cycle_deadlock(tmp_path: Path) -> None:
    cfg_file = tmp_path / "buffer_deadlock.yaml"
    cfg_file.write_text(BUFFER_CYCLE_YAML, encoding="utf-8")

    summary = run_episode(cfg_file)
    assert summary.status == "deadlocked"
    assert summary.is_deadlocked is True
    assert summary.deadlock_diagnosis is not None
    assert summary.deadlock_diagnosis["deadlock_type"] == "buffer_cycle"
    assert "involved_entities" in summary.deadlock_diagnosis
    assert "buf-A" in summary.deadlock_diagnosis["involved_entities"]
    assert "buf-B" in summary.deadlock_diagnosis["involved_entities"]
    assert "capacities" in summary.deadlock_diagnosis
    assert "ownership" in summary.deadlock_diagnosis
    assert "wait_edges" in summary.deadlock_diagnosis
    assert len(summary.deadlock_diagnosis["wait_edges"]) > 0
    assert "cycle" in summary.deadlock_diagnosis
    assert len(summary.deadlock_diagnosis["cycle"]) > 0


def test_e2e_stalled_production_despite_irrelevant_scheduled_events(tmp_path: Path) -> None:
    # A deadlocked episode with recurring telemetry scheduled every 500ms
    yaml_with_telemetry = BUFFER_CYCLE_YAML.replace(
        'max_interval_without_progress: "5s"',
        'max_interval_without_progress: "5s"\ntelemetry:\n  enabled: true\n  sample_interval: "500ms"',
    )
    cfg_file = tmp_path / "stalled_with_telemetry.yaml"
    cfg_file.write_text(yaml_with_telemetry, encoding="utf-8")

    summary = run_episode(cfg_file)
    assert summary.status == "deadlocked"
    assert summary.is_deadlocked is True
    assert summary.deadlock_diagnosis is not None
    # Confirm it stopped at maximum interval without domain progress rather than running forever
    assert summary.simulated_time_ns <= 15_000_000_000


def test_e2e_false_positive_avoidance(tmp_path: Path) -> None:
    # Normal operation with a long duration (30s).
    # Configured max_interval_without_progress is 10s.
    # The active operation is finite waiting, NOT a deadlock!
    cfg_file = tmp_path / "long_op_finite_waiting.yaml"
    cfg_file.write_text(
        """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0s
  end_condition:
    type: "all_units_terminal"
deadlock:
  enabled: true
  max_interval_without_progress: "10s"
material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "st-1"
      kind: "station"
      operations:
        - id: "op-1"
          duration: "30s"
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
      output_ports: [{id: "out", port_type: "part", direction: "output"}]
    - id: "sink-1"
      kind: "sink"
      input_ports: [{id: "in", port_type: "part", direction: "input"}]
  routes:
    - id: "r-src-st"
      source_node_id: "src-1"
      source_port_id: "out"
      target_node_id: "st-1"
      target_port_id: "in"
      transit_time: "1s"
    - id: "r-st-sink"
      source_node_id: "st-1"
      source_port_id: "out"
      target_node_id: "sink-1"
      target_port_id: "in"
      transit_time: "1s"
production_units:
  - id: "u-1"
    variant: "v-1"
""",
        encoding="utf-8",
    )

    summary = run_episode(cfg_file)
    assert summary.status == "completed"
    assert summary.deadlock_diagnosis is None
    assert summary.production_units[0].state == "terminal"


def test_e2e_cli_output_machine_readable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Run deadlocked episode via CLI and verify structured JSON output
    cfg_file = tmp_path / "cli_deadlock.yaml"
    cfg_file.write_text(BUFFER_CYCLE_YAML, encoding="utf-8")

    stdout_capture = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout_capture)

    exit_code = cli_main(["run", str(cfg_file)])
    assert exit_code == 0

    output_str = stdout_capture.getvalue()
    parsed = json.loads(output_str)
    assert parsed["status"] == "deadlocked"
    assert parsed["is_deadlocked"] is True
    assert "deadlock_diagnosis" in parsed
    assert parsed["deadlock_diagnosis"]["deadlock_type"] == "buffer_cycle"
    assert "capacities" in parsed["deadlock_diagnosis"]
    assert "ownership" in parsed["deadlock_diagnosis"]
    assert "wait_edges" in parsed["deadlock_diagnosis"]


def test_e2e_artifact_writer_and_audit_log(tmp_path: Path) -> None:
    # Run with output_dir and verify audit log records deadlock
    cfg_file = tmp_path / "audit_deadlock.yaml"
    out_dir = tmp_path / "run_artifacts"
    cfg_file.write_text(BUFFER_CYCLE_YAML, encoding="utf-8")

    summary = run_episode(cfg_file, output_dir=out_dir)
    assert summary.status == "deadlocked"

    # Verify manifest
    manifest_file = out_dir / "manifest.json"
    assert manifest_file.is_file()
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["status"] == "deadlocked"

    # Verify audit log contains deadlock record
    audit_file = out_dir / "audit.jsonl"
    lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").strip().splitlines()]
    deadlock_records = [rec for rec in lines if rec["event_type"] == "deadlock"]
    assert len(deadlock_records) == 1
    assert deadlock_records[0]["details"]["deadlock_type"] == "buffer_cycle"

    # Verify run inspection reports status
    inspection = inspect(out_dir)
    assert inspection.status == "deadlocked"
    assert inspection.has_incomplete_marker is False

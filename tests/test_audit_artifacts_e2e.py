from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pytest

from industrialsim.application import run_episode

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


def test_run_creates_atomic_result_directory_and_rejects_overwrite(tmp_path: Path) -> None:
    run_dir = tmp_path / "test_run_01"

    summary = run_episode(MINIMAL_VALID_YAML, output_dir=run_dir)
    assert summary.status == "completed"

    # Verify directory and core artifact files exist
    assert run_dir.is_dir()
    manifest_file = run_dir / "manifest.json"
    assert manifest_file.is_file()
    summary_file = run_dir / "summary.json"
    assert summary_file.is_file()
    resolved_config_file = run_dir / "resolved_config.yaml"
    assert resolved_config_file.is_file()
    audit_file = run_dir / "audit.jsonl"
    assert audit_file.is_file()
    assert (run_dir / "checkpoints" / "final_checkpoint.json").is_file()

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["model_hash"] != ""
    assert manifest["config_hash"] != ""

    # Attempting to run into an existing completed run directory must raise FileExistsError
    with pytest.raises(FileExistsError, match="already exists and is completed"):
        run_episode(MINIMAL_VALID_YAML, output_dir=run_dir)


def test_interrupted_run_remains_visibly_incomplete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from industrialsim.application import EpisodeEngine

    run_dir = tmp_path / "interrupted_run"

    # Simulate a crash/interruption during engine execution
    def crash_run(self: EpisodeEngine, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Simulated process crash or power interruption")

    monkeypatch.setattr(EpisodeEngine, "run", crash_run)

    with pytest.raises(RuntimeError, match="Simulated process crash"):
        run_episode(MINIMAL_VALID_YAML, output_dir=run_dir)

    # Artifact directory exists and is visibly incomplete
    assert run_dir.is_dir()
    incomplete_marker = run_dir / ".incomplete"
    assert incomplete_marker.is_file()

    manifest_file = run_dir / "manifest.json"
    assert manifest_file.is_file()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["status"] == "incomplete"
    assert manifest["completed_at"] is None

    # summary.json was not written because run did not complete
    summary_file = run_dir / "summary.json"
    assert not summary_file.exists()


def test_manifest_contains_comprehensive_reproducibility_metadata(tmp_path: Path) -> None:
    run_dir = tmp_path / "metadata_run"
    summary = run_episode(MINIMAL_VALID_YAML, output_dir=run_dir)
    assert summary.status == "completed"

    manifest_path = run_dir / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Runtime metadata
    runtime = manifest["runtime"]
    assert runtime["implementation"] == "CPython"
    assert runtime["version"].startswith("3.12")
    assert isinstance(runtime["platform"], str) and len(runtime["platform"]) > 0

    # Library metadata
    libs = manifest["libraries"]
    assert "pydantic" in libs
    assert "ruamel-yaml" in libs

    # Schema & kernel versions
    assert manifest["schema_version"] == "1.0"
    assert manifest["kernel_version"] == "1.0"

    # Hashes
    assert len(manifest["model_hash"]) == 64
    assert len(manifest["config_hash"]) == 64
    assert manifest["result_hash"] == summary.result_hash

    # Seed
    assert manifest["seed"] == 42

    # Plugin metadata
    assert isinstance(manifest["plugin_metadata"], dict)

    # Calibration metadata
    cal = manifest["calibration"]
    assert cal["is_calibrated"] is False
    assert "synthetic" in cal["notes"].lower()

    # Lifecycle timestamps
    assert manifest["status"] == "completed"
    assert isinstance(manifest["created_at"], str)
    assert isinstance(manifest["completed_at"], str)


def test_lossless_ordered_audit_log(tmp_path: Path) -> None:
    from test_decision_simulation_e2e import BASE_DECISION_YAML
    from industrialsim.decisions import (
        DecisionProvider,
        DecisionBatch,
        DecisionBatchResponse,
        DecisionProvenance,
        BufferReorderAction,
    )
    from industrialsim.audit import load_audit_log

    class CustomBufferProvider(DecisionProvider):
        def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
            actions = []
            for req in batch.requests:
                if "buffer" in req.request_type:
                    occupant_ids = [occ.unit_id for occ in req.observation.occupants]
                    actions.append(
                        BufferReorderAction(
                            target_id=req.target_id,
                            new_order=list(reversed(occupant_ids)),
                        )
                    )
            return DecisionBatchResponse(
                batch_id=batch.batch_id,
                provenance=DecisionProvenance(
                    episode_id=batch.episode_id,
                    batch_id=batch.batch_id,
                    provider_id="test-buffer-agent",
                    model_id="test-model-v1",
                    prompt_id="prompt-reorder-001",
                ),
                actions=actions,
            )

    run_dir1 = tmp_path / "audit_run_1"
    run_dir2 = tmp_path / "audit_run_2"

    provider1 = CustomBufferProvider()
    summary1 = run_episode(BASE_DECISION_YAML, decision_provider=provider1, output_dir=run_dir1)
    assert summary1.status == "completed"

    provider2 = CustomBufferProvider()
    summary2 = run_episode(BASE_DECISION_YAML, decision_provider=provider2, output_dir=run_dir2)
    assert summary2.status == "completed"

    records1 = load_audit_log(run_dir1)
    records2 = load_audit_log(run_dir2)

    # 1. Non-empty and deterministic identical count
    assert len(records1) > 0
    assert len(records1) == len(records2)

    # 2. Deterministic ordering: sequence IDs are strictly 0, 1, ..., N-1 and times monotonic
    last_seq = -1
    last_time = -1
    for rec in records1:
        assert rec.record_id == last_seq + 1
        assert rec.simulated_time_ns >= last_time
        last_seq = rec.record_id
        last_time = rec.simulated_time_ns

    # 3. Determinism across runs: every record matches bit-for-bit (except creation timestamps)
    for r1, r2 in zip(records1, records2):
        assert r1.record_id == r2.record_id
        assert r1.simulated_time_ns == r2.simulated_time_ns
        assert r1.event_type == r2.event_type
        assert r1.episode_id == r2.episode_id
        assert r1.entity_ids == r2.entity_ids
        assert r1.details == r2.details

    # 4. Critical lifecycle & decision events are all present:
    event_types = {r.event_type for r in records1}
    assert "unit_lifecycle" in event_types
    assert "decision_request" in event_types
    assert "decision_action" in event_types
    assert "validation_outcome" in event_types

    # 5. Correlation fields present on decision events
    decision_records = [r for r in records1 if r.event_type.startswith("decision_") or r.event_type == "validation_outcome"]
    for d_rec in decision_records:
        assert d_rec.batch_id is not None
        assert d_rec.episode_id is not None
        if d_rec.event_type == "decision_action":
            assert d_rec.provenance is not None
            assert d_rec.provenance["provider_id"] == "test-buffer-agent"

    # 6. Unit lifecycle transitions track all units
    unit_lifecycle_recs = [r for r in records1 if r.event_type == "unit_lifecycle"]
    unit_ids_seen = {r.entity_ids[0] for r in unit_lifecycle_recs if r.entity_ids}
    assert "u-0" in unit_ids_seen
    assert "u-1" in unit_ids_seen
    assert "u-2" in unit_ids_seen


def test_audit_log_records_fallback_when_validation_fails(tmp_path: Path) -> None:
    from test_decision_simulation_e2e import BASE_DECISION_YAML
    from industrialsim.audit import load_audit_log

    run_dir = tmp_path / "fallback_audit_run"

    # Running with no provider triggers fallback policy FIFO on buffer threshold
    summary = run_episode(BASE_DECISION_YAML, decision_provider=None, output_dir=run_dir)
    assert summary.status == "completed"

    records = load_audit_log(run_dir)

    validation_records = [r for r in records if r.event_type == "validation_outcome"]
    assert len(validation_records) > 0
    assert validation_records[0].details["is_valid"] is False

    fallback_records = [r for r in records if r.event_type == "fallback"]
    assert len(fallback_records) > 0
    assert fallback_records[0].details["fallback_policy"] == "fifo"

    fallback_actions = [
        r for r in records
        if r.event_type == "decision_action" and r.provenance and "fallback" in r.provenance.get("provider_id", "")
    ]
    assert len(fallback_actions) > 0
    prov = fallback_actions[0].provenance
    assert prov is not None
    assert prov["provider_id"] == "fallback-fifo"


def test_branch_checkpoint_artifacts_and_stable_relationships(tmp_path: Path) -> None:
    from test_branch_counterfactual_decisions_e2e import BASE_DECISION_YAML
    from industrialsim.application import create_checkpoint, branch_checkpoint
    from industrialsim.decisions import BufferReorderAction
    from industrialsim.audit import load_audit_log

    branch_out = tmp_path / "branch_experiment_01"
    cp = create_checkpoint(BASE_DECISION_YAML, pause_at_decision_batch=True)

    action_1 = [BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-2"])]
    action_2 = [BufferReorderAction(target_id="buf-1", new_order=["u-2", "u-1"])]

    comp = branch_checkpoint(cp, [action_1, action_2], output_dir=branch_out)

    assert branch_out.is_dir()
    manifest_file = branch_out / "manifest.json"
    assert manifest_file.is_file()
    root_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert root_manifest["status"] == "completed"
    assert root_manifest["decision_batch_id"] == comp.decision_batch_id
    assert root_manifest["checkpoint_config_hash"] == cp.config_hash
    assert len(root_manifest["branches"]) == 2

    comp_summary_file = branch_out / "comparison_summary.json"
    assert comp_summary_file.is_file()
    assert (branch_out / "resolved_config.yaml").is_file()
    assert root_manifest["model_hash"] == cp.model_hash
    assert root_manifest["config_hash"] == cp.config_hash
    parent_cp_file = branch_out / "checkpoints" / "parent_checkpoint.json"
    assert parent_cp_file.is_file()

    # Each branch must have its own isolated artifact folder with stable parent relationships
    for b in comp.branches:
        branch_dir = branch_out / "branches" / b.branch_id
        assert branch_dir.is_dir()
        assert (branch_dir / "checkpoints" / "final_checkpoint.json").is_file()

        b_manifest_file = branch_dir / "manifest.json"
        assert b_manifest_file.is_file()
        b_manifest = json.loads(b_manifest_file.read_text(encoding="utf-8"))
        assert b_manifest["branch_id"] == b.branch_id
        assert b_manifest["checkpoint_hash"] == cp.config_hash
        assert b_manifest["status"] == "completed"

        # audit.jsonl in branch has all records tagged with branch_id
        b_audit_file = branch_dir / "audit.jsonl"
        assert b_audit_file.is_file()
        records = load_audit_log(branch_dir)
        assert len(records) > 0
        for rec in records:
            assert rec.branch_id == b.branch_id

        # Branch summary
        b_summary_file = branch_dir / "summary.json"
        assert b_summary_file.is_file()

    # Overwrite protection applies to branch comparison runs as well
    with pytest.raises(FileExistsError, match="already exists and is completed"):
        branch_checkpoint(cp, [action_1, action_2], output_dir=branch_out)


def test_inspect_completed_run_and_incomplete_run(tmp_path: Path) -> None:
    from industrialsim.application import run_episode, create_checkpoint, save_checkpoint, inspect
    from industrialsim.audit import inspect_run, RunInspection
    from industrialsim.checkpoint import CheckpointInspection

    # 1. Inspect completed run
    run_dir = tmp_path / "completed_run"
    summary = run_episode(MINIMAL_VALID_YAML, output_dir=run_dir)
    assert summary.status == "completed"

    insp = inspect_run(run_dir)
    assert isinstance(insp, RunInspection)
    assert insp.status == "completed"
    assert insp.is_complete is True
    assert insp.has_incomplete_marker is False
    assert insp.has_summary is True
    assert insp.has_resolved_config is True
    assert insp.has_audit_log is True
    assert insp.audit_record_count > 0
    assert insp.has_checkpoints is True
    assert insp.checkpoint_count == 1
    assert insp.simulated_time_ns == 10_000_000_000
    assert insp.schema_version == "1.0"
    assert insp.kernel_version == "1.0"
    assert insp.calibration_metadata["is_calibrated"] is False
    assert "cpython" in insp.runtime_metadata.get("implementation", "").lower()

    # Dict serialization
    insp_dict = insp.to_dict()
    assert insp_dict["is_complete"] is True
    assert insp_dict["status"] == "completed"
    assert insp_dict["audit_record_count"] == insp.audit_record_count

    # 2. Inspect incomplete run
    incomplete_dir = tmp_path / "incomplete_run"
    incomplete_dir.mkdir()
    (incomplete_dir / ".incomplete").write_text("in_progress\n", encoding="utf-8")
    (incomplete_dir / "manifest.json").write_text(
        json.dumps({
            "run_id": "ep-incomplete",
            "status": "incomplete",
            "schema_version": "1.0",
            "kernel_version": "1.0",
            "created_at": "2026-09-20T00:00:00Z",
            "completed_at": None,
            "seed": 42,
            "calibration": {"is_calibrated": False},
        }),
        encoding="utf-8",
    )
    (incomplete_dir / "audit.jsonl").write_text(
        '{"record_id":0,"simulated_time_ns":0,"event_type":"unit_lifecycle","episode_id":"ep-incomplete","entity_ids":["u-0"],"details":{}}\n',
        encoding="utf-8",
    )

    insp_inc = inspect_run(incomplete_dir)
    assert insp_inc.status == "incomplete"
    assert insp_inc.is_complete is False
    assert insp_inc.has_incomplete_marker is True
    assert insp_inc.has_summary is False
    assert insp_inc.audit_record_count == 1

    # 3. Unified inspect dispatch
    # Run directory
    insp_unified_dir = inspect(run_dir)
    assert isinstance(insp_unified_dir, RunInspection)
    assert insp_unified_dir.is_complete is True

    # Manifest file
    insp_unified_manifest = inspect(run_dir / "manifest.json")
    assert isinstance(insp_unified_manifest, RunInspection)
    assert insp_unified_manifest.is_complete is True

    # Incomplete dir
    insp_unified_inc = inspect(incomplete_dir)
    assert isinstance(insp_unified_inc, RunInspection)
    assert insp_unified_inc.is_complete is False

    # Checkpoint file
    cp = create_checkpoint(MINIMAL_VALID_YAML, at_time_ns=5_000_000_000)
    cp_file = tmp_path / "checkpoint.json"
    save_checkpoint(cp, cp_file)

    insp_unified_cp = inspect(cp_file)
    assert isinstance(insp_unified_cp, CheckpointInspection)
    assert insp_unified_cp.simulated_time_ns == 5_000_000_000


def test_cli_inspect_run_artifacts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from industrialsim.cli import main

    run_dir = tmp_path / "cli_run"
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(MINIMAL_VALID_YAML, encoding="utf-8")

    exit_code = main(["run", str(cfg_file), "--output-dir", str(run_dir)])
    assert exit_code == 0
    capsys.readouterr()  # Flush stdout from run command

    # Inspect the completed run directory via CLI
    exit_code = main(["inspect", str(run_dir)])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "completed"
    assert data["is_complete"] is True
    assert data["has_summary"] is True
    assert data["has_incomplete_marker"] is False
    assert data["audit_record_count"] > 0
    assert data["calibration_metadata"]["is_calibrated"] is False

    # Create incomplete directory and inspect via CLI
    inc_dir = tmp_path / "cli_incomplete"
    inc_dir.mkdir()
    (inc_dir / ".incomplete").write_text("in_progress\n", encoding="utf-8")
    (inc_dir / "manifest.json").write_text(
        json.dumps({
            "run_id": "ep-inc",
            "status": "incomplete",
            "schema_version": "1.0",
            "kernel_version": "1.0",
            "created_at": "2026-09-20T00:00:00Z",
            "completed_at": None,
            "seed": 42,
        }),
        encoding="utf-8",
    )
    exit_code = main(["inspect", str(inc_dir)])
    assert exit_code == 0
    captured = capsys.readouterr()
    data_inc = json.loads(captured.out)
    assert data_inc["status"] == "incomplete"
    assert data_inc["is_complete"] is False
    assert data_inc["has_incomplete_marker"] is True


def test_replay_audit_log_lossless_under_load(tmp_path: Path) -> None:
    from industrialsim.audit import load_audit_log

    load_yaml = """
schema_version: "1.0"
seed: 999
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"
plant:
  id: "plant-1"
  name: "Assembly Plant"
  areas:
    - id: "area-1"
      name: "Main Area"
      halls:
        - id: "hall-1"
          name: "Main Hall"
material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      hall_id: "hall-1"
      output_ports:
        - id: "p-out"
          port_type: "vehicle"
          direction: "output"
    - id: "st-1"
      kind: "station"
      hall_id: "hall-1"
      output_capacity: 0
      operations:
        - id: "op-fast"
          duration: "1s"
      input_ports:
        - id: "p-in"
          port_type: "vehicle"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "vehicle"
          direction: "output"
    - id: "buf-1"
      kind: "buffer"
      hall_id: "hall-1"
      capacity: 5
      input_ports:
        - id: "p-in"
          port_type: "vehicle"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "vehicle"
          direction: "output"
    - id: "st-2"
      kind: "station"
      hall_id: "hall-1"
      output_capacity: 0
      operations:
        - id: "op-assembly"
          duration: "2s"
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
      hall_id: "hall-1"
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
    - id: "r-st1-buf"
      source_node_id: "st-1"
      source_port_id: "p-out"
      target_node_id: "buf-1"
      target_port_id: "p-in"
    - id: "r-buf-st2"
      source_node_id: "buf-1"
      source_port_id: "p-out"
      target_node_id: "st-2"
      target_port_id: "p-in"
    - id: "r-st2-snk"
      source_node_id: "st-2"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"
production_units:
""" + "\n".join(
        f"""  - id: "unit-{i:02d}"
    variant: "sedan"
    release_time: "{i}s"
"""
        for i in range(20)
    )

    dir1 = tmp_path / "load_run_1"
    dir2 = tmp_path / "load_run_2"

    sum1 = run_episode(load_yaml, output_dir=dir1)
    sum2 = run_episode(load_yaml, output_dir=dir2)

    assert sum1.status == "completed"
    assert sum2.status == "completed"
    assert sum1.result_hash == sum2.result_hash
    assert sum1.simulated_time_ns == sum2.simulated_time_ns

    records1 = load_audit_log(dir1)
    records2 = load_audit_log(dir2)

    # 1. High volume of records generated under load
    assert len(records1) >= 100
    assert len(records1) == len(records2)

    # 2. Deterministic replay: bit-for-bit event equality
    for idx, (r1, r2) in enumerate(zip(records1, records2)):
        assert r1.record_id == idx
        assert r2.record_id == idx
        assert r1.simulated_time_ns == r2.simulated_time_ns
        assert r1.event_type == r2.event_type
        assert r1.episode_id == r2.episode_id
        assert r1.entity_ids == r2.entity_ids
        assert r1.details == r2.details

    # 3. Monotonic order guarantees: time never goes backwards
    for i in range(len(records1) - 1):
        assert records1[i].record_id < records1[i + 1].record_id
        assert records1[i].simulated_time_ns <= records1[i + 1].simulated_time_ns

    # 4. Trajectory integrity: every unit's full lifecycle is recorded
    for i in range(20):
        uid = f"unit-{i:02d}"
        unit_recs = [r for r in records1 if uid in r.entity_ids]
        transitions = [r.details.get("transition") for r in unit_recs if "transition" in r.details]

        assert "released" in transitions
        assert "operation_started" in transitions
        assert "operation_completed" in transitions
        assert "terminal" in transitions


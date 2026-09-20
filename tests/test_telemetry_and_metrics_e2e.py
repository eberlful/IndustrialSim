from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pytest

from ruamel.yaml import YAML

from industrialsim.application import EpisodeEngine, run_episode, validate_config
from industrialsim.config import SimulationConfig

_yaml = YAML(typ="safe", pure=True)


WARMUP_METRICS_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  warm_up_time: "5s"
  end_condition:
    type: "all_units_terminal"
production_units:
  - id: "unit-early"
    variant: "sedan"
    release_time: "0s"
    due_date: "10s"
  - id: "unit-eval"
    variant: "sedan"
    release_time: "5s"
    due_date: "8s"
stations:
  - id: "st-assembly"
    operations:
      - id: "op-assembly"
        duration: "4s"
"""


def test_run_reports_raw_metrics_with_warmup_exclusion() -> None:
    """Verifies Requirement 1 & 8: Raw metrics reported without objective weights, excluding warm-up period."""
    summary = run_episode(WARMUP_METRICS_YAML)
    assert summary.status == "completed"

    # Verify raw metrics exist on summary and in to_dict()
    assert hasattr(summary, "raw_metrics")
    metrics = summary.raw_metrics
    assert isinstance(metrics, dict)
    assert summary.to_dict()["raw_metrics"] == metrics

    # Required raw metric keys
    expected_keys = {
        "good_output",
        "lead_time_ns",
        "wip",
        "scrap",
        "downtime_ns",
        "lateness_ns",
        "resource_utilization",
    }
    assert expected_keys.issubset(metrics.keys())

    # Warm-up exclusion: unit-early finished at 4s (< 5s warm_up_time_ns).
    # unit-eval released at 5s, finished at 9s (> 5s warm_up_time_ns).
    # Therefore, post-warmup good_output must be 1 (unit-eval only).
    assert metrics["good_output"] == 1
    assert metrics["scrap"] == 0
    assert metrics["wip"] == 0

    # Lead time for unit-eval: 9s - 5s = 4s (4_000_000_000 ns)
    assert metrics["lead_time_ns"] == 4_000_000_000

    # Lateness for unit-eval: finished at 9s, due at 8s -> 1s lateness (1_000_000_000 ns)
    assert metrics["lateness_ns"] == 1_000_000_000


REWARD_POLICY_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"
reward_policy:
  id: "throughput_and_quality"
  components:
    - name: "good_output"
      weight: 100.0
      scale: 10.0
    - name: "lead_time_ns"
      weight: -2.0
      scale: 1000000000.0  # 1s scale
    - name: "scrap"
      weight: -50.0
      scale: 1.0
production_units:
  - id: "u-1"
    variant: "sedan"
    release_time: "0s"
stations:
  - id: "st-1"
    operations:
      - id: "op-1"
        duration: "5s"
"""


def test_reward_policy_normalization_and_weight_exposure(tmp_path: Path) -> None:
    """Verifies Requirement 2: Configured Reward Policy normalizes components and exposes every weight in resolved config."""
    run_dir = tmp_path / "reward_run"
    summary = run_episode(REWARD_POLICY_YAML, output_dir=run_dir)
    assert summary.status == "completed"

    # Verify scalar reward is computed on summary
    assert hasattr(summary, "reward")
    assert summary.reward is not None

    # Expected calculation:
    # good_output = 1 -> norm = 1 / 10.0 = 0.1 -> contribution = 100.0 * 0.1 = 10.0
    # lead_time_ns = 5_000_000_000 -> norm = 5e9 / 1e9 = 5.0 -> contribution = -2.0 * 5.0 = -10.0
    # scrap = 0 -> norm = 0.0 -> contribution = 0.0
    # Total reward = 10.0 - 10.0 + 0.0 = 0.0
    assert summary.reward == pytest.approx(0.0)
    assert summary.reward_breakdown["good_output"] == pytest.approx(10.0)
    assert summary.reward_breakdown["lead_time_ns"] == pytest.approx(-10.0)
    assert summary.reward_breakdown["scrap"] == pytest.approx(0.0)

    # Verify resolved experiment configuration exposes all weights and components
    resolved_config_path = run_dir / "resolved_config.yaml"
    assert resolved_config_path.is_file()
    from ruamel.yaml import YAML
    _yaml = YAML(typ="safe", pure=True)
    resolved_data = _yaml.load(resolved_config_path.read_text(encoding="utf-8"))
    assert "reward_policy" in resolved_data
    policy_data = resolved_data["reward_policy"]
    assert policy_data["id"] == "throughput_and_quality"
    assert len(policy_data["components"]) == 3
    names_and_weights = {c["name"]: c["weight"] for c in policy_data["components"]}
    assert names_and_weights == {"good_output": 100.0, "lead_time_ns": -2.0, "scrap": -50.0}


HARD_CONSTRAINT_TERMINATION_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"
hard_constraints:
  terminate_on_violation: true
  max_scrap: 0
reward_policy:
  id: "reward_with_scrap_weight"
  components:
    - name: "good_output"
      weight: 10.0
      scale: 1.0
production_units:
  - id: "unit-scrapped"
    variant: "sedan"
    release_time: "0s"
    quality_state: "scrapped"
  - id: "unit-later"
    variant: "sedan"
    release_time: "10s"
stations:
  - id: "st-1"
    operations:
      - id: "op-1"
        duration: "5s"
"""


def test_hard_constraint_independent_termination_and_reward_separation(tmp_path: Path) -> None:
    """Verifies Requirement 3: Hard-constraint violations remain separate from scalar Reward and independently terminate an Episode."""
    run_dir = tmp_path / "hard_constraint_run"
    summary = run_episode(HARD_CONSTRAINT_TERMINATION_YAML, output_dir=run_dir)

    # Episode terminated independently due to hard-constraint violation
    assert summary.status == "aborted"
    assert summary.is_aborted is True
    assert "HARD_CONSTRAINT_VIOLATION" in (summary.abort_reason or "")

    # Hard constraints are exposed and not satisfied
    assert hasattr(summary, "hard_constraints")
    assert summary.hard_constraints["satisfied"] is False
    assert any("max_scrap" in str(v) or v.get("code") == "MAX_SCRAP_EXCEEDED" for v in summary.hard_constraints["violations"])

    # Reward remains separate from hard constraint violation
    assert hasattr(summary, "reward")
    # unit-later was never processed because episode was terminated early at 0s
    assert summary.raw_metrics["good_output"] == 0
    assert summary.reward == 0.0

    # Audit log records the hard constraint violation losslessly
    audit_file = run_dir / "audit.jsonl"
    assert audit_file.is_file()
    records = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    violation_events = [r for r in records if r["event_type"] == "hard_constraint_violation"]
    assert len(violation_events) >= 1
    assert violation_events[0]["details"]["code"] == "MAX_SCRAP_EXCEEDED"


TELEMETRY_SAMPLING_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"
telemetry:
  enabled: true
  sample_interval: "2s"
  domain_events: ["operation_completed"]
  batch_size: 10
production_units:
  - id: "unit-1"
    variant: "sedan"
    release_time: "0s"
stations:
  - id: "st-1"
    operations:
      - id: "op-1"
        duration: "5s"
"""


def test_state_telemetry_sampling_and_runtime_toggle(tmp_path: Path) -> None:
    """Verifies Requirement 4: State telemetry sampled at configured intervals, domain events, and runtime enable/disable."""
    run_dir = tmp_path / "telemetry_run"
    summary = run_episode(TELEMETRY_SAMPLING_YAML, output_dir=run_dir)
    assert summary.status == "completed"

    # Parquet telemetry files exist in run directory under telemetry/
    telemetry_dir = run_dir / "telemetry"
    assert telemetry_dir.is_dir()
    parquet_files = sorted(telemetry_dir.glob("metrics_fragment_*.parquet"))
    assert len(parquet_files) >= 1

    import pyarrow.parquet as pq
    tables = [pq.read_table(f) for f in parquet_files]
    total_records = sum(t.num_rows for t in tables)
    assert total_records > 0

    # Combine tables to inspect samples
    import pyarrow as pa
    combined = pa.concat_tables(tables)
    pydict = combined.to_pydict()

    # Verify interval samples exist
    sample_types = pydict["sample_type"]
    assert "interval" in sample_types
    # Verify domain event samples exist
    assert "domain_event" in sample_types

    # Find the domain event sample
    domain_event_indices = [i for i, st in enumerate(sample_types) if st == "domain_event"]
    assert len(domain_event_indices) >= 1
    assert any(pydict["event_name"][i] == "operation_completed" for i in domain_event_indices)

    # Verify runtime enable/disable on engine
    engine = EpisodeEngine.create(SimulationConfig.model_validate(_yaml.load(TELEMETRY_SAMPLING_YAML)))
    assert engine.is_telemetry_enabled is True
    engine.disable_telemetry()
    assert engine.is_telemetry_enabled is False
    engine.enable_telemetry()
    assert engine.is_telemetry_enabled is True


BACKPRESSURE_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"
telemetry:
  enabled: true
  sample_interval: "500ms"
  domain_events: ["operation_completed", "unit_released"]
  batch_size: 100
  backpressure:
    policy: "thin"
    max_queue_size: 4
    thin_factor: 2
production_units:
  - id: "u-1"
    variant: "sedan"
    release_time: "0s"
  - id: "u-2"
    variant: "sedan"
    release_time: "1s"
  - id: "u-3"
    variant: "sedan"
    release_time: "2s"
stations:
  - id: "st-1"
    operations:
      - id: "op-1"
        duration: "3s"
"""


def test_telemetry_backpressure_thins_samples_without_dropping_audit_records(tmp_path: Path) -> None:
    """Verifies Requirement 5: Optional telemetry obeys explicit backpressure policy (thinning) but cannot drop critical audit records."""
    run_dir = tmp_path / "backpressure_run"
    summary = run_episode(BACKPRESSURE_YAML, output_dir=run_dir)
    assert summary.status == "completed"

    # Verify inspection reports thinned samples
    from industrialsim.audit import inspect_run
    insp = inspect_run(run_dir)
    assert insp.thinned_samples_count > 0, f"Expected thinned samples, got {insp.thinned_samples_count}"

    # Verify manifest reports thinned_samples_count
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["thinned_samples_count"] == insp.thinned_samples_count
    assert manifest["thinned_samples_count"] > 0

    # CRITICAL AUDIT LOG: lossless ordered records must NOT drop any critical records!
    from industrialsim.audit import load_audit_log
    records = load_audit_log(run_dir)
    assert len(records) > 0

    # Strictly monotonic record_id with 0 gaps
    for idx, rec in enumerate(records):
        assert rec.record_id == idx

    # Verify all 3 units completed their lifecycle and have critical records
    unit_ids = {"u-1", "u-2", "u-3"}
    seen_units = {r.entity_ids[0] for r in records if r.event_type == "unit_lifecycle" and r.entity_ids}
    assert unit_ids.issubset(seen_units)

    seen_terminal = {
        r.entity_ids[0]
        for r in records
        if r.event_type == "unit_lifecycle"
        and r.entity_ids
        and (r.details.get("state") == "terminal" or r.details.get("transition") == "terminal")
    }
    assert unit_ids.issubset(seen_terminal)


FRAGMENT_ROTATION_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"
telemetry:
  enabled: true
  sample_interval: "1s"
  domain_events: ["operation_completed", "decision_batch"]
  batch_size: 2
production_units:
  - id: "u-1"
    variant: "sedan"
    release_time: "0s"
  - id: "u-2"
    variant: "sedan"
    release_time: "1s"
stations:
  - id: "st-1"
    operations:
      - id: "op-1"
        duration: "3s"
decision_triggers:
  - id: "trig-safe"
    trigger_type: "safe_point"
    target_id: "st-1"
    times_ns: [0, 2000000000, 4000000000]
    on_failure: "fallback"
    fallback_policy: "baseline"
"""


def test_parquet_fragment_rotation_bounded_batches_and_schema_stability(tmp_path: Path) -> None:
    """Verifies Requirements 6 & 7: Closed rotating Parquet fragments with stable schemas derived from canonical data, with incomplete protection."""
    import pyarrow.parquet as pq
    from industrialsim.telemetry import METRICS_TELEMETRY_SCHEMA, TRAINING_RECORDS_SCHEMA
    from industrialsim.audit import inspect_run, load_audit_log

    run_dir = tmp_path / "rotation_run"
    summary = run_episode(FRAGMENT_ROTATION_YAML, output_dir=run_dir)
    assert summary.status == "completed"

    telemetry_dir = run_dir / "telemetry"
    assert telemetry_dir.is_dir()

    # 1. Bounded batch rotation: with batch_size=2 and multiple interval/event samples,
    # multiple closed metrics fragments should have been rotated!
    metrics_fragments = sorted(telemetry_dir.glob("metrics_fragment_*.parquet"))
    assert len(metrics_fragments) >= 2, f"Expected at least 2 metrics fragments, got {len(metrics_fragments)}"

    training_fragments = sorted(telemetry_dir.glob("training_fragment_*.parquet"))
    assert len(training_fragments) >= 1

    # 2. Closed fragment integrity: no .tmp files exist in telemetry directory
    tmp_files = list(telemetry_dir.glob("*.tmp"))
    assert len(tmp_files) == 0, f"Found unclosed temporary fragment files: {tmp_files}"

    # 3. Schema stability across fragments
    for frag in metrics_fragments:
        t = pq.read_table(frag)
        # All columns and types must match METRICS_TELEMETRY_SCHEMA
        assert t.schema.names == METRICS_TELEMETRY_SCHEMA.names
        for field in METRICS_TELEMETRY_SCHEMA:
            assert t.schema.field(field.name).type == field.type

    for frag in training_fragments:
        t = pq.read_table(frag)
        assert t.schema.names == TRAINING_RECORDS_SCHEMA.names
        for field in TRAINING_RECORDS_SCHEMA:
            assert t.schema.field(field.name).type == field.type

    # 4. Manifest advertising: only closed fragments are advertised
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    advertised = manifest["telemetry_fragments"]
    expected_frags = [f"telemetry/{f.name}" for f in metrics_fragments] + [f"telemetry/{f.name}" for f in training_fragments]
    assert set(advertised) == set(expected_frags)

    # 5. Derivation from canonical run data:
    # Combine metrics fragments and compare with summary and audit log
    import pyarrow as pa
    combined_metrics = pa.concat_tables([pq.read_table(f) for f in metrics_fragments])
    metrics_pydict = combined_metrics.to_pydict()

    # Final recorded good_output in parquet equals summary.raw_metrics["good_output"]
    assert metrics_pydict["good_output"][-1] == summary.raw_metrics["good_output"]
    # Final recorded scrap in parquet equals summary.raw_metrics["scrap"]
    assert metrics_pydict["scrap"][-1] == summary.raw_metrics["scrap"]

    # Training records derive from decision requests in audit log
    combined_training = pa.concat_tables([pq.read_table(f) for f in training_fragments])
    training_pydict = combined_training.to_pydict()
    audit_records = load_audit_log(run_dir)
    audit_batch_ids = {r.batch_id for r in audit_records if r.batch_id}
    parquet_batch_ids = set(training_pydict["batch_id"])
    assert parquet_batch_ids.issubset(audit_batch_ids)

    # 6. Incomplete fragment safety: simulate an incomplete .parquet.tmp file created during an unfinalized run
    fake_incomplete_file = telemetry_dir / "metrics_fragment_99999.parquet.tmp"
    fake_incomplete_file.write_text("corrupted partial binary data", encoding="utf-8")

    # inspect_run must NOT advertise fake_incomplete_file as part of complete dataset
    insp = inspect_run(run_dir)
    assert not any("99999" in f for f in insp.telemetry_fragments)


def test_reward_policy_minimize_direction_and_target() -> None:
    from industrialsim.application import _compute_reward
    from industrialsim.config import RewardComponentConfig, RewardPolicyConfig

    policy = RewardPolicyConfig(
        id="test_dir_target",
        components=[
            RewardComponentConfig(
                name="scrap",
                weight=10.0,
                scale=1.0,
                direction="minimize",
            ),
            RewardComponentConfig(
                name="good_output",
                weight=5.0,
                scale=2.0,
                target=10.0,
            ),
        ],
    )
    raw_metrics = {"scrap": 2, "good_output": 6}
    # scrap: norm_val = -(2 - 0) / 1 = -2.0 -> c_reward = 10.0 * -2.0 = -20.0
    # good_output: norm_val = -abs(6 - 10) / 2.0 = -2.0 -> c_reward = 5.0 * -2.0 = -10.0
    total, breakdown = _compute_reward(raw_metrics, policy)
    assert total == pytest.approx(-30.0)
    assert breakdown["scrap"] == pytest.approx(-20.0)
    assert breakdown["good_output"] == pytest.approx(-10.0)


def test_branch_checkpoint_exports_telemetry_parquet(tmp_path: Path) -> None:
    from industrialsim.application import branch_checkpoint, create_checkpoint
    from industrialsim.decisions import BufferReorderAction

    config_yaml = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"
telemetry:
  enabled: true
  sample_interval: "1s"
  batch_size: 2
production_units:
  - id: "u-1"
    variant: "sedan"
    release_time: "0s"
  - id: "u-2"
    variant: "sedan"
    release_time: "1s"
stations:
  - id: "st-1"
    operations:
      - id: "op-1"
        duration: "3s"
decision_triggers:
  - id: "trig-1"
    trigger_type: "safe_point"
    target_id: "st-1"
    times_ns: [0]
    on_failure: "fallback"
    fallback_policy: "baseline"
"""
    cp = create_checkpoint(config_yaml, pause_at_decision_batch=True)
    out_dir = tmp_path / "branch_telemetry_run"

    actions_a = [BufferReorderAction(target_id="st-1", new_order=["u-1", "u-2"])]
    actions_b = [BufferReorderAction(target_id="st-1", new_order=["u-2", "u-1"])]

    comp = branch_checkpoint(cp, [actions_a, actions_b], output_dir=out_dir)
    assert len(comp.branches) == 2

    # Check that branches output telemetry Parquet files
    for b in comp.branches:
        branch_telemetry_dir = out_dir / "branches" / b.branch_id / "telemetry"
        assert branch_telemetry_dir.is_dir()
        metrics_frags = list(branch_telemetry_dir.glob("metrics_fragment_*.parquet"))
        assert len(metrics_frags) >= 1
        branch_manifest = json.loads((out_dir / "branches" / b.branch_id / "manifest.json").read_text(encoding="utf-8"))
        assert len(branch_manifest["telemetry_fragments"]) >= 1


def test_hard_constraints_downtime_termination(tmp_path: Path) -> None:
    downtime_yaml = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"
hard_constraints:
  terminate_on_violation: true
  max_downtime_ns: 1000000000  # 1 second
machines:
  - id: "m-1"
    capacity: 1
    planned_disruptions:
      - start_time: "1s"
        duration: "3s"
production_units:
  - id: "u-1"
    variant: "sedan"
    release_time: "0s"
stations:
  - id: "st-1"
    operations:
      - id: "op-1"
        duration: "10s"
        required_machines: ["m-1"]
"""
    summary = run_episode(downtime_yaml)
    assert summary.status == "aborted"
    assert summary.is_aborted is True
    assert "HARD_CONSTRAINT_VIOLATION: max_downtime limit exceeded" in (summary.abort_reason or "")
    assert summary.hard_constraints["satisfied"] is False
    assert any(v.get("code") == "MAX_DOWNTIME_EXCEEDED" for v in summary.hard_constraints["violations"])







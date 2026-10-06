from __future__ import annotations

import json
from pathlib import Path
import pytest

from industrialsim.application import validate_config
from industrialsim.config import SimulationConfig, CalibrationConfig


def test_calibration_config_uncalibrated_synthetic_parameters() -> None:
    yaml_snippet = """
schema_version: "1.0"
seed: 42
calibration:
  is_calibrated: false
  notes: "synthetic reference parameters; not calibrated for quantitative real-world prediction"
  uncalibrated_parameters:
    - "cycle_times"
    - "degradation_rates"
    - "failure_rates"
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"
stations:
  - id: "st-1"
    operations:
      - id: "op-1"
        duration: "5s"
production_units:
  - id: "u-1"
    variant: "sedan"
"""
    result = validate_config(yaml_snippet)
    assert result.is_valid is True
    assert result.config is not None
    assert result.config.calibration is not None
    assert result.config.calibration.is_calibrated is False
    assert "cycle_times" in result.config.calibration.uncalibrated_parameters


def test_reference_automotive_plant_configuration_structure() -> None:
    yaml_path = Path(__file__).resolve().parents[1] / "examples/reference_automotive_plant.yaml"
    assert yaml_path.exists(), f"Reference plant configuration file {yaml_path} does not exist"

    result = validate_config(yaml_path)
    assert result.is_valid is True, f"Validation errors: {result.errors}"
    cfg = result.config
    assert cfg is not None

    # Plant structure: Areas and Halls
    assert cfg.plant is not None
    area_ids = {a.id for a in cfg.plant.areas}
    assert "area-body-construction" in area_ids
    assert "area-paint-application" in area_ids
    assert "area-final-assembly" in area_ids

    # Material Flow: Stations and Buffers
    assert cfg.material_flow is not None
    nodes_by_id = {n.id: n for n in cfg.material_flow.nodes}

    # Parallel body shop stations
    assert "st-body-1" in nodes_by_id and nodes_by_id["st-body-1"].kind == "station"
    assert "st-body-2" in nodes_by_id and nodes_by_id["st-body-2"].kind == "station"

    # Paint shop: pretreatment, paint booth, drying
    assert "st-paint-pretreat" in nodes_by_id and nodes_by_id["st-paint-pretreat"].kind == "station"
    assert "st-paint-booth" in nodes_by_id and nodes_by_id["st-paint-booth"].kind == "station"
    assert "st-paint-drying" in nodes_by_id and nodes_by_id["st-paint-drying"].kind == "station"

    # Sequential final assembly
    assert "st-assembly-1" in nodes_by_id and nodes_by_id["st-assembly-1"].kind == "station"
    assert "st-assembly-2" in nodes_by_id and nodes_by_id["st-assembly-2"].kind == "station"

    # Quality Inspection and Rework
    assert "st-inspect" in nodes_by_id and nodes_by_id["st-inspect"].kind == "station"
    assert "st-rework" in nodes_by_id and nodes_by_id["st-rework"].kind == "station"

    # Bounded Buffers
    buffers = [n for n in cfg.material_flow.nodes if n.kind == "buffer"]
    assert len(buffers) >= 3
    for b in buffers:
        assert b.capacity is not None and b.capacity > 0

    # Shared vehicles
    assert len(cfg.vehicles) >= 2 or len(cfg.vehicle_pools) >= 1

    # Production Plan: at least two product variants over a production week
    variants = {p.variant for p in cfg.production_plan}
    assert len(variants) >= 2
    assert "sedan" in variants
    assert "suv" in variants
    for p in cfg.production_plan:
        assert p.release_time_ns >= 0
        assert p.due_date_ns is not None and p.due_date_ns > p.release_time_ns

    # Production week duration
    assert cfg.episode.end_condition.type == "max_time"
    assert cfg.episode.end_condition.max_time_ns is not None
    # At least 5 days (5 * 86400s = 432_000s = 432_000_000_000_000 ns)
    assert cfg.episode.end_condition.max_time_ns >= 432_000_000_000_000

    # Warm-up period configured
    assert cfg.episode.warm_up_time_ns > 0

    # Machines degrade, fail, and require maintenance
    assert len(cfg.machines) >= 4
    machines_with_degradation = [m for m in cfg.machines if m.degradation is not None]
    assert len(machines_with_degradation) >= 2
    machines_with_maintenance = [m for m in cfg.machines if m.maintenance is not None]
    assert len(machines_with_maintenance) >= 1
    # Maintenance requires workers
    maint_worker_reqs = [
        m for m in machines_with_maintenance if m.maintenance is not None and any(req.qualification == "maintenance" for req in m.maintenance.required_workers)
    ]
    assert len(maint_worker_reqs) >= 1

    # Workers follow qualifications and shifts/breaks
    assert len(cfg.workers) >= 3
    qualifications = {q for w in cfg.workers for q in w.qualifications}
    assert "maintenance" in qualifications
    workers_with_shifts = [w for w in cfg.workers if len(w.shifts) > 0]
    assert len(workers_with_shifts) >= 2
    assert any(len(s.breaks) > 0 for w in workers_with_shifts for s in w.shifts)

    # Imperfect quality findings (inspection sensitivity < 1.0 or false_positive_rate > 0.0)
    all_stations = list(cfg.stations) + [n for n in cfg.material_flow.nodes if n.kind == "station"]
    inspect_station = next(s for s in all_stations if s.id == "st-inspect")
    assert any(
        op.inspection is not None
        and (op.inspection.sensitivity < 1.0 or op.inspection.false_positive_rate > 0.0)
        for op in inspect_station.operations
    )

    # Synthetic parameters identified as uncalibrated
    assert cfg.calibration.is_calibrated is False
    assert len(cfg.calibration.uncalibrated_parameters) > 0


def test_compare_policies_structured_metrics_and_rewards(tmp_path: Path) -> None:
    from industrialsim.application import compare_policies, PolicyComparisonResult
    from industrialsim.decisions import (
        DecisionBatch,
        DecisionBatchResponse,
        DecisionProvider,
        DecisionProvenance,
        BufferReorderAction,
    )

    class CustomPriorityDecisionProvider(DecisionProvider):
        """In-process custom decision provider that prioritizes reversing buffer order."""

        def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
            actions = []
            for req in batch.requests:
                if req.action_schema == "buffer_reorder":
                    obs = req.observation
                    occupants = getattr(obs, "occupants", [])
                    # Reverse order
                    new_order = [occ.unit_id for occ in reversed(occupants)]
                    actions.append(
                        BufferReorderAction(
                            target_id=req.target_id,
                            new_order=new_order,
                        )
                    )
            return DecisionBatchResponse(
                batch_id=batch.batch_id,
                provenance=DecisionProvenance(
                    episode_id=batch.episode_id,
                    branch_id=batch.branch_id,
                    batch_id=batch.batch_id,
                    provider_id="custom-priority-provider",
                ),
                actions=actions,
            )

    yaml_content = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  warm_up_time: "1s"
  end_condition:
    type: "all_units_terminal"
material_flow:
  nodes:
    - id: "src"
      kind: "source"
      output_ports: [{id: "out", port_type: "conveyor", direction: "output"}]
    - id: "buf-1"
      kind: "buffer"
      capacity: 5
      input_ports: [{id: "in", port_type: "conveyor", direction: "input"}]
      output_ports: [{id: "out", port_type: "conveyor", direction: "output"}]
    - id: "st-1"
      kind: "station"
      input_ports: [{id: "in", port_type: "conveyor", direction: "input"}]
      output_ports: [{id: "out", port_type: "conveyor", direction: "output"}]
      operations:
        - id: "op-assembly"
          duration: "5s"
    - id: "snk"
      kind: "sink"
      input_ports: [{id: "in", port_type: "conveyor", direction: "input"}]
  routes:
    - id: "r-src-buf"
      source_node_id: "src"
      source_port_id: "out"
      target_node_id: "buf-1"
      target_port_id: "in"
    - id: "r-buf-st1"
      source_node_id: "buf-1"
      source_port_id: "out"
      target_node_id: "st-1"
      target_port_id: "in"
    - id: "r-st1-snk"
      source_node_id: "st-1"
      source_port_id: "out"
      target_node_id: "snk"
      target_port_id: "in"
production_units:
  - id: "u-1"
    variant: "sedan"
    release_time: "0s"
    due_date: "12s"
  - id: "u-2"
    variant: "sedan"
    release_time: "0s"
    due_date: "12s"
decision_triggers:
  - id: "trig-buf-1"
    buffer_id: "buf-1"
    threshold: 2
    direction: "rising"
    on_failure: "fallback"
    fallback_policy: "fifo"
reward_policy:
  id: "lead_time_policy"
  components:
    - name: "good_output"
      weight: 100.0
      scale: 1.0
    - name: "lead_time_ns"
      weight: -1.0
      scale: 1000000000.0
"""

    out_dir = tmp_path / "comparison_run"
    provider = CustomPriorityDecisionProvider()
    comparison = compare_policies(yaml_content, decision_provider=provider, output_dir=out_dir)

    assert isinstance(comparison, PolicyComparisonResult)
    assert comparison.config_hash is not None
    assert comparison.seed == 42
    assert comparison.baseline_summary.status == "completed"
    assert comparison.provider_summary.status == "completed"

    # Structured metrics comparison
    assert "good_output" in comparison.metrics_comparison
    assert "lead_time_ns" in comparison.metrics_comparison
    assert "wip" in comparison.metrics_comparison
    assert "scrap" in comparison.metrics_comparison
    assert "lateness_ns" in comparison.metrics_comparison
    assert "baseline" in comparison.metrics_comparison["good_output"]
    assert "provider" in comparison.metrics_comparison["good_output"]
    assert "delta" in comparison.metrics_comparison["good_output"]

    # Reward comparison
    assert "baseline_reward" in comparison.reward_comparison
    assert "provider_reward" in comparison.reward_comparison
    assert "delta_reward" in comparison.reward_comparison
    assert "breakdown_comparison" in comparison.reward_comparison

    # Hard constraints comparison
    assert "baseline_satisfied" in comparison.hard_constraints_comparison
    assert "provider_satisfied" in comparison.hard_constraints_comparison

    # Fallback comparison
    assert "baseline_fallbacks" in comparison.fallbacks_comparison
    assert "provider_fallbacks" in comparison.fallbacks_comparison

    # Status comparison
    assert comparison.status_comparison["baseline_status"] == "completed"
    assert comparison.status_comparison["provider_status"] == "completed"
    assert comparison.status_comparison["baseline_result_hash"] != ""
    assert comparison.status_comparison["provider_result_hash"] != ""

    # Output directory artifacts
    assert out_dir.is_dir()
    assert (out_dir / "comparison_summary.json").is_file()
    assert (out_dir / "manifest.json").is_file()
    assert (out_dir / "baseline" / "summary.json").is_file()
    assert (out_dir / "provider" / "summary.json").is_file()
    assert not (out_dir / ".incomplete").exists()

    from industrialsim.application import inspect
    inspection = inspect(out_dir)
    assert inspection.is_complete is True
    assert inspection.status == "completed"
    assert inspection.has_summary is True
    assert inspection.has_resolved_config is True


def test_reference_plant_determinism_repeated_execution_hashes() -> None:
    from industrialsim.application import run_episode

    yaml_path = Path(__file__).resolve().parents[1] / "examples/reference_automotive_plant.yaml"
    summary1 = run_episode(yaml_path)
    summary2 = run_episode(yaml_path)

    assert summary1.status == "completed"
    assert summary2.status == "completed"
    assert summary1.result_hash == summary2.result_hash
    assert summary1.events_processed == summary2.events_processed
    assert summary1.simulated_time_ns == summary2.simulated_time_ns
    assert summary1.simulated_time_ns == 432_000_000_000_000  # 5 days
    assert summary1.raw_metrics == summary2.raw_metrics
    assert summary1.reward == summary2.reward
    assert summary1.to_dict() == summary2.to_dict()


def test_reference_plant_baseline_vs_decision_provider_comparison(tmp_path: Path) -> None:
    from industrialsim.application import compare_policies, PolicyComparisonResult, inspect
    from industrialsim.decisions import (
        DecisionBatch,
        DecisionBatchResponse,
        DecisionProvider,
        DecisionProvenance,
        BufferReorderAction,
    )

    class ReversingBufferDecisionProvider(DecisionProvider):
        """In-process Decision Provider that reverses buffer order on decision requests."""

        def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
            actions = []
            for req in batch.requests:
                if req.action_schema == "buffer_reorder":
                    obs = req.observation
                    occupants = getattr(obs, "occupants", [])
                    new_order = [occ.unit_id for occ in reversed(occupants)]
                    actions.append(
                        BufferReorderAction(
                            target_id=req.target_id,
                            new_order=new_order,
                        )
                    )
            return DecisionBatchResponse(
                batch_id=batch.batch_id,
                provenance=DecisionProvenance(
                    episode_id=batch.episode_id,
                    branch_id=batch.branch_id,
                    batch_id=batch.batch_id,
                    provider_id="reversing-decision-provider",
                ),
                actions=actions,
            )

    yaml_path = Path(__file__).resolve().parents[1] / "examples/reference_automotive_plant.yaml"
    out_dir = tmp_path / "reference_plant_comparison"

    comparison = compare_policies(
        yaml_path,
        decision_provider=ReversingBufferDecisionProvider(),
        output_dir=out_dir,
    )

    assert isinstance(comparison, PolicyComparisonResult)
    assert comparison.config_hash is not None
    assert comparison.seed == 42

    # Both policies execute over the production week
    assert comparison.baseline_summary.status == "completed"
    assert comparison.provider_summary.status == "completed"
    assert comparison.baseline_summary.simulated_time_ns == 432_000_000_000_000
    assert comparison.provider_summary.simulated_time_ns == 432_000_000_000_000

    # Structured metrics comparison
    metrics_comp = comparison.metrics_comparison
    for key in ("good_output", "lead_time_ns", "wip", "scrap", "downtime_ns", "lateness_ns", "resource_utilization"):
        assert key in metrics_comp
        assert "baseline" in metrics_comp[key]
        assert "provider" in metrics_comp[key]
        assert "delta" in metrics_comp[key]

    # Warm-up exclusion: 100 units total released across the week.
    # 25 units were released before warm_up_time (8h). Post-warmup output: 68 good + 7 scrap = 75 total.
    assert comparison.baseline_summary.raw_metrics["good_output"] == 68
    assert comparison.provider_summary.raw_metrics["good_output"] == 68
    assert comparison.baseline_summary.raw_metrics["scrap"] == 7
    assert comparison.provider_summary.raw_metrics["scrap"] == 7

    # Downstream operations show rework and scrap
    rework_st = next(s for s in comparison.baseline_summary.stations if s.id == "st-rework")
    assert rework_st.operations_completed > 0
    inspect_st = next(s for s in comparison.baseline_summary.stations if s.id == "st-inspect")
    assert inspect_st.scrapped_count > 0

    # Machines degrade, fail, and require maintenance competing for workers
    welder_m = next(m for m in comparison.baseline_summary.machines if m.id == "m-body-welder-1")
    assert welder_m.failure_count > 0 or welder_m.total_failed_time_ns > 0
    assert welder_m.maintenance_count > 0 or welder_m.total_maintenance_time_ns > 0

    # Reward comparison
    assert comparison.reward_comparison["baseline_reward"] is not None
    assert comparison.reward_comparison["provider_reward"] is not None
    assert comparison.reward_comparison["delta_reward"] is not None
    assert "breakdown_comparison" in comparison.reward_comparison

    # Hard constraints comparison
    assert comparison.hard_constraints_comparison["baseline_satisfied"] is True
    assert comparison.hard_constraints_comparison["provider_satisfied"] is True

    # Fallback behavior reflected in summaries
    assert "baseline_fallbacks" in comparison.fallbacks_comparison
    assert "provider_fallbacks" in comparison.fallbacks_comparison

    # Terminal statuses and hashes
    assert comparison.status_comparison["baseline_status"] == "completed"
    assert comparison.status_comparison["provider_status"] == "completed"
    assert len(comparison.status_comparison["baseline_result_hash"]) == 64
    assert len(comparison.status_comparison["provider_result_hash"]) == 64

    # Run manifest contains uncalibrated synthetic parameter declaration
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["type"] == "policy_comparison"
    assert manifest["status"] == "completed"
    assert manifest["calibration"]["is_calibrated"] is False
    assert len(manifest["calibration"]["uncalibrated_parameters"]) > 0
    assert "station_cycle_times" in manifest["calibration"]["uncalibrated_parameters"]

    # Telemetry and audit artifacts created in child run directories
    baseline_dir = out_dir / "baseline"
    provider_dir = out_dir / "provider"
    assert (baseline_dir / "audit.jsonl").is_file()
    assert (provider_dir / "audit.jsonl").is_file()
    assert len(list(baseline_dir.glob("telemetry/*.parquet"))) > 0
    assert len(list(provider_dir.glob("telemetry/*.parquet"))) > 0

    insp = inspect(out_dir)
    assert insp.is_complete is True


def test_reference_plant_counterfactual_branching_artifacts(tmp_path: Path) -> None:
    from industrialsim.application import create_checkpoint, branch_checkpoint, inspect
    from industrialsim.decisions import BufferReorderAction

    yaml_path = Path(__file__).resolve().parents[1] / "examples/reference_automotive_plant.yaml"
    cp = create_checkpoint(yaml_path, pause_at_decision_batch=True)

    # Paused at Decision Batch
    assert cp.simulated_time_ns > 0
    pending_reqs = cp.domain_state["decision_coordinator"]["pending_requests"]
    assert len(pending_reqs) > 0
    first_req = pending_reqs[0]
    target_buffer = first_req["target_id"]
    occupants = [occ["unit_id"] for occ in first_req["observation"]["occupants"]]
    assert len(occupants) >= 2

    # Two controlled Counterfactual Branches
    action_alt_a = [BufferReorderAction(target_id=target_buffer, new_order=list(occupants))]
    action_alt_b = [BufferReorderAction(target_id=target_buffer, new_order=list(reversed(occupants)))]

    out_dir = tmp_path / "reference_plant_branches"
    comp_result = branch_checkpoint(cp, [action_alt_a, action_alt_b], output_dir=out_dir)

    assert len(comp_result.branches) == 2
    b1 = comp_result.branches[0]
    b2 = comp_result.branches[1]

    # Both branches run to completion
    assert b1.summary is not None
    assert b2.summary is not None
    assert b1.summary.status == "completed"
    assert b2.summary.status == "completed"
    assert b1.summary.simulated_time_ns == 432_000_000_000_000
    assert b2.summary.simulated_time_ns == 432_000_000_000_000

    # Deterministic result hashes are distinct across branches
    assert b1.result_hash != b2.result_hash
    assert len(b1.result_hash) == 64
    assert len(b2.result_hash) == 64

    # Metrics and hard constraints present
    assert "good_output" in b1.raw_metrics
    assert "lead_time_ns" in b1.raw_metrics
    assert b1.hard_constraints["satisfied"] is True
    assert b2.hard_constraints["satisfied"] is True

    # Complete audit and telemetry artifacts generated in branch directories
    for b in (b1, b2):
        b_dir = out_dir / "branches" / b.branch_id
        assert b_dir.is_dir()
        assert (b_dir / "audit.jsonl").is_file()
        assert (b_dir / "summary.json").is_file()
        assert (b_dir / "manifest.json").is_file()
        assert (b_dir / "checkpoints" / "final_checkpoint.json").is_file()

        # Rotating parquet telemetry fragments
        parquet_files = list(b_dir.glob("telemetry/*.parquet"))
        assert len(parquet_files) > 0

        # Inspect branch
        insp = inspect(b_dir)
        assert insp.is_complete is True
        assert insp.status == "completed"
        assert insp.telemetry_record_count > 0
        assert insp.audit_record_count > 0

    # Root comparison artifacts
    assert (out_dir / "comparison_summary.json").is_file()
    assert (out_dir / "manifest.json").is_file()
    assert (out_dir / "checkpoints" / "parent_checkpoint.json").is_file()
    root_insp = inspect(out_dir)
    assert root_insp.is_complete is True
    assert len(root_insp.branches) == 2





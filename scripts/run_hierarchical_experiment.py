#!/usr/bin/env python3
"""
Execution script for Hierarchical Forecasting & Multi-Level Decision Experiment (EXP-0003).
Runs:
1. Baseline simulation with telemetry recording.
2. Offline forecasting evaluation comparing TimesFM 3, Linear Trend, Moving Average, and Naive.
3. Kausal Counterfactual Branching at T=120s across:
   - Branch A: Reactive Baseline
   - Branch B: Statistical Baseline (Moving Average)
   - Branch C: TimesFM 3 Foundation Model
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import numpy as np
from ruamel.yaml import YAML

from industrialsim.application import EpisodeEngine
from industrialsim.audit import AuditLogger, RunArtifactWriter
from industrialsim.checkpoint import save_checkpoint
from industrialsim.config import SimulationConfig
from industrialsim.decisions import BaselineDecisionProvider
from industrialsim.forecasting.baselines import (
    LinearTrendCovariateForecaster,
    MovingAverageForecaster,
    NaiveLastValueForecaster,
)
from industrialsim.forecasting.benchmark import run_offline_benchmark
from industrialsim.forecasting.hierarchical_provider import HierarchicalPredictiveProvider
from industrialsim.forecasting.timesfm_adapter import TimesFM3Adapter
from industrialsim.telemetry import TelemetryManager


def main() -> None:
    output_base = Path("runs/hierarchical_eval")
    if output_base.exists():
        shutil.rmtree(output_base)
    output_base.mkdir(parents=True, exist_ok=True)

    yaml = YAML(typ="safe")
    with open("examples/hierarchical_forecasting_plant.yaml") as f:
        data = yaml.load(f)
    cfg = SimulationConfig.model_validate(data)

    print("=" * 70)
    print("STEP 1: Executing Base Simulation to T=120s and Checkpointing...")
    print("=" * 70)

    root_dir = output_base / "root_run"
    root_telemetry = TelemetryManager(
        output_dir=root_dir,
        config=cfg.telemetry,
        episode_id="ep-hierarchical-root",
    )
    root_audit = AuditLogger()

    plan_entries = [p.model_dump() for p in cfg.production_plan]
    root_engine = EpisodeEngine.create(
        cfg=cfg,
        decision_provider=BaselineDecisionProvider(),
        audit_logger=root_audit,
        telemetry_manager=root_telemetry,
    )

    # Step until 120s
    checkpoint_time_ns = 120_000_000_000
    while root_engine.kernel.queue_size > 0:
        peek_t = root_engine.kernel.peek_next_time()
        if peek_t is not None and peek_t > checkpoint_time_ns:
            break
        root_engine.kernel.step()
        if root_engine.decision_coordinator.has_pending():
            root_engine._process_decision_batch()

    checkpoint = root_engine.create_checkpoint()
    print(f"Checkpoint created at T = {checkpoint.simulated_time_ns / 1e9:.1f}s")
    print(f"Events processed so far: {checkpoint.events_processed}")

    # =========================================================================
    # STEP 2: Counterfactual Branching at T=120s
    # =========================================================================
    print("\n" + "=" * 70)
    print("STEP 2: Running 3 Counterfactual Branches from Checkpoint T=120s...")
    print("=" * 70)

    branches = [
        ("branch_a_reactive", "Reactive Baseline (FIFO / Nominal)", BaselineDecisionProvider()),
        (
            "branch_b_statistical",
            "Statistical Baseline (Moving Average)",
            HierarchicalPredictiveProvider(
                forecaster=MovingAverageForecaster(window_size=8),
                provider_id="stat_ma_provider",
                model_id="moving_average",
                future_plan_entries=plan_entries,
            ),
        ),
        (
            "branch_c_timesfm3",
            "TimesFM 3 Foundation Model",
            HierarchicalPredictiveProvider(
                forecaster=TimesFM3Adapter(),
                provider_id="timesfm3_hierarchical",
                model_id="timesfm-3",
                future_plan_entries=plan_entries,
            ),
        ),
    ]

    branch_results: dict[str, dict] = {}

    for branch_id, label, provider in branches:
        branch_dir = output_base / "branches" / branch_id
        branch_dir.mkdir(parents=True, exist_ok=True)
        branch_telemetry = TelemetryManager(
            output_dir=branch_dir,
            config=cfg.telemetry,
            episode_id=f"ep-{branch_id}",
        )
        branch_audit = AuditLogger()

        engine = EpisodeEngine.restore(
            checkpoint=checkpoint,
            config=cfg,
            decision_provider=provider,
            audit_logger=branch_audit,
            telemetry_manager=branch_telemetry,
        )
        engine.decision_coordinator.branch_id = branch_id

        summary = engine.run()
        branch_telemetry.close()

        metrics = summary.raw_metrics
        branch_results[branch_id] = {
            "label": label,
            "result_hash": summary.result_hash,
            "events_processed": summary.events_processed,
            "good_output": metrics["good_output"],
            "scrap": metrics["scrap"],
            "wip": metrics["wip"],
            "lead_time_s": metrics["lead_time_ns"] / 1e9,
            "lateness_s": metrics["lateness_ns"] / 1e9,
            "downtime_s": metrics["downtime_ns"] / 1e9,
            "decision_batches": len(summary.decision_batches),
            "strategic_cost": summary.total_strategic_cost,
        }

        # Save audit logs
        audit_path = branch_dir / "audit.jsonl"
        with open(audit_path, "w") as f:
            for rec in branch_audit.records:
                f.write(rec.model_dump_json() + "\n")

        print(
            f"[{branch_id}] {label:40s} -> Good: {metrics['good_output']} | "
            f"LeadTime: {metrics['lead_time_ns']/1e9:6.1f}s | "
            f"Lateness: {metrics['lateness_ns']/1e9:6.1f}s | "
            f"Batches: {len(summary.decision_batches):2d} | "
            f"Hash: {summary.result_hash[:12]}..."
        )

    # Save branch comparison JSON
    with open(output_base / "branch_comparison.json", "w") as f:
        json.dump(branch_results, f, indent=2)

    # =========================================================================
    # STEP 3: Multi-Level Offline Forecasting Benchmark
    # =========================================================================
    print("\n" + "=" * 70)
    print("STEP 3: Running Multi-Level Offline Forecasting Benchmark...")
    print("=" * 70)

    # Use telemetry from branch A as realistic evaluation trajectory
    telemetry_dir = output_base / "branches" / "branch_a_reactive" / "telemetry"

    benchmark_summary = run_offline_benchmark(
        telemetry_dir=telemetry_dir,
        context_len=16,
        horizon=16,
        stride=4,
    )

    benchmark_path = output_base / "benchmark_results.json"
    with open(benchmark_path, "w") as f:
        json.dump(benchmark_summary, f, indent=2)

    print("Offline Benchmark Completed! Overall Performance Across Targets:")
    for m_name, res in benchmark_summary.get("models", {}).items():
        ov = res["overall"]
        print(
            f"  {m_name:30s} | MAE: {ov['mae']:6.3f} | WAPE: {ov['wape']:6.3f} | "
            f"CRPS: {ov['crps']:6.3f} | Mean WQL: {ov['mean_wql']:6.3f}"
        )

    print("\n" + "=" * 70)
    print("Experiment EXP-0003 completed successfully!")
    print(f"Artifacts saved in {output_base}")
    print("=" * 70)


if __name__ == "__main__":
    main()

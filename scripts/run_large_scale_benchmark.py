#!/usr/bin/env python3
"""
Execution script for Large-Scale Multi-Horizon, Multi-Seed Benchmark (EXP-0004).
Evaluates:
1. Multi-Seed Base Simulations (Seeds: 42, 101, 2026) over 90m (5,400s, 140 units).
2. Multi-Horizon Rolling-Window Forecasting Benchmark (H in {8, 16, 32, 64, 128}) across 8 models:
   - TimesFM-3 (Multivariate)
   - TimesFM-3 (Univariate)
   - Linear Trend + Covariates
   - Exponential Smoothing (Damped)
   - Moving Average (w=8, w=16, w=32)
   - Naive Persistence
3. Cross-Seed Aggregation (Mean ± Std Dev) for all metrics and horizons.
4. Closed-Loop Causal Counterfactual Branching at T=240s:
   - Branch A: Reactive Baseline (FIFO / Nominal)
   - Branch B: Statistical Baseline (Exponential Smoothing / Damped Trend)
   - Branch C: TimesFM 3 Foundation Model
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import shutil
from typing import Any
import numpy as np
from ruamel.yaml import YAML

from industrialsim.application import EpisodeEngine
from industrialsim.audit import AuditLogger
from industrialsim.config import SimulationConfig
from industrialsim.decisions import BaselineDecisionProvider
from industrialsim.forecasting.baselines import (
    ExponentialSmoothingForecaster,
    MovingAverageForecaster,
)
from industrialsim.forecasting.benchmark import run_offline_benchmark
from industrialsim.forecasting.hierarchical_provider import HierarchicalPredictiveProvider
from industrialsim.forecasting.timesfm_adapter import TimesFM3Adapter
from industrialsim.telemetry import TelemetryManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_benchmark(
    config_path: str = "examples/large_scale_benchmark_plant.yaml",
    output_dir: str = "runs/large_scale_benchmark",
    seeds: tuple[int, ...] = (42, 101, 2026),
    horizons: tuple[int, ...] = (8, 16, 32, 64, 128),
    context_len: int = 64,
    stride: int = 16,
    branch_checkpoint_time_s: float = 240.0,
) -> dict[str, Any]:
    output_base = Path(output_dir)
    output_base.mkdir(parents=True, exist_ok=True)

    yaml = YAML(typ="safe")
    with open(config_path, encoding="utf-8") as f:
        raw_cfg = yaml.load(f)

    seed_benchmark_results: dict[int, dict[str, Any]] = {}
    seed_simulation_summaries: dict[int, dict[str, Any]] = {}

    print("\n" + "=" * 90)
    print("PHASE 1: Multi-Seed Full Trajectory Simulations (Seeds: 42, 101, 2026)")
    print("=" * 90)

    for seed in seeds:
        print(f"\n--- Running Full Simulation for Seed {seed} (Duration: 90m / 5400s) ---")
        cfg_dict = dict(raw_cfg)
        cfg_dict["seed"] = seed
        cfg = SimulationConfig.model_validate(cfg_dict)

        seed_dir = output_base / f"seed_{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        telemetry = TelemetryManager(
            output_dir=seed_dir,
            config=cfg.telemetry,
            episode_id=f"ep-large-scale-seed-{seed}",
        )
        audit = AuditLogger()

        engine = EpisodeEngine.create(
            cfg=cfg,
            decision_provider=BaselineDecisionProvider(),
            audit_logger=audit,
            telemetry_manager=telemetry,
        )

        sim_summary = engine.run()
        telemetry.close()

        m = sim_summary.raw_metrics
        print(
            f"Seed {seed} Complete: Good Output: {m.get('good_output', 0)} / 140 | "
            f"Scrap: {m.get('scrap', 0)} | WIP: {m.get('wip', 0)} | "
            f"LeadTime: {m.get('lead_time_ns', 0) / 1e9:.1f}s | "
            f"Events: {sim_summary.events_processed} | Hash: {sim_summary.result_hash[:12]}..."
        )

        seed_simulation_summaries[seed] = {
            "seed": seed,
            "result_hash": sim_summary.result_hash,
            "events_processed": sim_summary.events_processed,
            "good_output": m.get("good_output", 0),
            "scrap": m.get("scrap", 0),
            "wip": m.get("wip", 0),
            "lead_time_s": m.get("lead_time_ns", 0) / 1e9,
            "lateness_s": m.get("lateness_ns", 0) / 1e9,
            "downtime_s": m.get("downtime_ns", 0) / 1e9,
        }

        # Run multi-horizon benchmark on this seed's telemetry
        print(f"Running multi-horizon forecasting evaluation for Seed {seed}...")
        bench = run_offline_benchmark(
            telemetry_dir=seed_dir / "telemetry",
            context_len=context_len,
            horizons=horizons,
            stride=stride,
        )
        seed_benchmark_results[seed] = bench

        with open(seed_dir / "benchmark_report.json", "w", encoding="utf-8") as f:
            json.dump(bench, f, indent=2)

    # =========================================================================
    # PHASE 2: Multi-Horizon & Cross-Seed Aggregation
    # =========================================================================
    print("\n" + "=" * 90)
    print("PHASE 2: Cross-Seed Metric Aggregation Across Horizons H in {8, 16, 32, 64, 128}")
    print("=" * 90)

    model_names = list(seed_benchmark_results[seeds[0]]["models"].keys())
    metric_keys = ["mae", "rmse", "wape", "crps", "mean_wql"]

    # Cross-seed aggregation by horizon and overall
    aggregated_benchmark: dict[str, Any] = {
        "seeds": list(seeds),
        "horizons": list(horizons),
        "context_len": context_len,
        "stride": stride,
        "models": {},
    }

    for model_name in model_names:
        model_agg: dict[str, Any] = {"by_horizon": {}, "overall": {}}

        # Aggregate overall across seeds
        for k in metric_keys:
            vals = [seed_benchmark_results[s]["models"][model_name]["overall"][k] for s in seeds]
            model_agg["overall"][k] = {
                "mean": float(np.mean(vals)),
                "std": float(np.std(vals)),
                "values": vals,
            }

        # Aggregate each horizon across seeds
        for h in horizons:
            h_str = str(h)
            model_agg["by_horizon"][h_str] = {}
            for k in metric_keys:
                h_vals = [
                    seed_benchmark_results[s]["models"][model_name]["by_horizon"][h_str]["overall"][k]
                    for s in seeds
                ]
                model_agg["by_horizon"][h_str][k] = {
                    "mean": float(np.mean(h_vals)),
                    "std": float(np.std(h_vals)),
                    "values": h_vals,
                }

        aggregated_benchmark["models"][model_name] = model_agg

    # Print summary table of cross-seed overall metrics
    print(f"\n{'Model':<32} | {'MAE (Mean±Std)':<18} | {'RMSE (Mean±Std)':<18} | {'CRPS (Mean±Std)':<18} | {'WQL (Mean±Std)':<18}")
    print("-" * 115)
    for model_name in sorted(model_names, key=lambda m: aggregated_benchmark["models"][m]["overall"]["crps"]["mean"]):
        ov = aggregated_benchmark["models"][model_name]["overall"]
        mae_str = f"{ov['mae']['mean']:.3f}±{ov['mae']['std']:.3f}"
        rmse_str = f"{ov['rmse']['mean']:.3f}±{ov['rmse']['std']:.3f}"
        crps_str = f"{ov['crps']['mean']:.3f}±{ov['crps']['std']:.3f}"
        wql_str = f"{ov['mean_wql']['mean']:.3f}±{ov['mean_wql']['std']:.3f}"
        print(f"{model_name:<32} | {mae_str:<18} | {rmse_str:<18} | {crps_str:<18} | {wql_str:<18}")
    print("-" * 115)

    # Print per-horizon CRPS comparison table
    print("\n" + "=" * 90)
    print("Per-Horizon CRPS Progression (H = 8, 16, 32, 64, 128)")
    print("=" * 90)
    h_header = " | ".join(f"H={h:<6}" for h in horizons)
    print(f"{'Model':<32} | {h_header}")
    print("-" * (35 + 10 * len(horizons)))
    for model_name in sorted(model_names, key=lambda m: aggregated_benchmark["models"][m]["overall"]["crps"]["mean"]):
        h_vals_str = " | ".join(
            f"{aggregated_benchmark['models'][model_name]['by_horizon'][str(h)]['crps']['mean']:<8.3f}"
            for h in horizons
        )
        print(f"{model_name:<32} | {h_vals_str}")
    print("-" * (35 + 10 * len(horizons)))

    with open(output_base / "cross_seed_benchmark_summary.json", "w", encoding="utf-8") as f:
        json.dump(aggregated_benchmark, f, indent=2)

    # =========================================================================
    # PHASE 3: Counterfactual Branching at T=240s (Seed 42)
    # =========================================================================
    print("\n" + "=" * 90)
    print(f"PHASE 3: Closed-Loop Counterfactual Branching at T={branch_checkpoint_time_s:.0f}s (Seed 42)")
    print("=" * 90)

    cfg_dict_42 = dict(raw_cfg)
    cfg_dict_42["seed"] = 42
    cfg_42 = SimulationConfig.model_validate(cfg_dict_42)
    plan_entries_42 = [p.model_dump() for p in cfg_42.production_plan]

    branch_base_dir = output_base / "counterfactual_branches"
    branch_base_dir.mkdir(parents=True, exist_ok=True)

    root_dir = branch_base_dir / "root"
    root_telemetry = TelemetryManager(
        output_dir=root_dir,
        config=cfg_42.telemetry,
        episode_id="ep-branch-root",
    )
    root_audit = AuditLogger()
    root_engine = EpisodeEngine.create(
        cfg=cfg_42,
        decision_provider=BaselineDecisionProvider(),
        audit_logger=root_audit,
        telemetry_manager=root_telemetry,
    )

    checkpoint_time_ns = int(branch_checkpoint_time_s * 1e9)
    while root_engine.kernel.queue_size > 0:
        peek_t = root_engine.kernel.peek_next_time()
        if peek_t is not None and peek_t > checkpoint_time_ns:
            break
        root_engine.kernel.step()
        if root_engine.decision_coordinator.has_pending():
            root_engine._process_decision_batch()

    branch_checkpoint = root_engine.create_checkpoint()
    print(f"Branch Checkpoint captured at T = {branch_checkpoint.simulated_time_ns / 1e9:.1f}s")
    print(f"Events processed up to checkpoint: {branch_checkpoint.events_processed}")

    branches = [
        (
            "branch_a_reactive",
            "Branch A: Reactive Baseline (FIFO / Local Nominal)",
            BaselineDecisionProvider(),
        ),
        (
            "branch_b_exponential_smoothing",
            "Branch B: Exponential Smoothing (Damped Trend)",
            HierarchicalPredictiveProvider(
                forecaster=ExponentialSmoothingForecaster(alpha=0.3, beta=0.1, phi=0.95),
                provider_id="exp_smooth_provider",
                model_id="exponential_smoothing",
                future_plan_entries=plan_entries_42,
            ),
        ),
        (
            "branch_c_timesfm3",
            "Branch C: TimesFM 3 Foundation Model (Hierarchical)",
            HierarchicalPredictiveProvider(
                forecaster=TimesFM3Adapter(patch_len=32),
                provider_id="timesfm3_provider",
                model_id="timesfm-3",
                future_plan_entries=plan_entries_42,
            ),
        ),
    ]

    branch_results: dict[str, Any] = {}

    for branch_id, label, provider in branches:
        b_dir = branch_base_dir / branch_id
        b_dir.mkdir(parents=True, exist_ok=True)
        b_telemetry = TelemetryManager(
            output_dir=b_dir,
            config=cfg_42.telemetry,
            episode_id=f"ep-{branch_id}",
        )
        b_audit = AuditLogger()

        engine = EpisodeEngine.restore(
            checkpoint=branch_checkpoint,
            config=cfg_42,
            decision_provider=provider,
            audit_logger=b_audit,
            telemetry_manager=b_telemetry,
        )
        engine.decision_coordinator.branch_id = branch_id

        summary = engine.run()
        b_telemetry.close()

        bm = summary.raw_metrics
        branch_results[branch_id] = {
            "label": label,
            "result_hash": summary.result_hash,
            "events_processed": summary.events_processed,
            "good_output": bm.get("good_output", 0),
            "scrap": bm.get("scrap", 0),
            "wip": bm.get("wip", 0),
            "lead_time_s": bm.get("lead_time_ns", 0) / 1e9,
            "lateness_s": bm.get("lateness_ns", 0) / 1e9,
            "downtime_s": bm.get("downtime_ns", 0) / 1e9,
            "decision_batches": len(summary.decision_batches),
            "strategic_cost": summary.total_strategic_cost,
        }

        # Save audit records
        with open(b_dir / "audit.jsonl", "w", encoding="utf-8") as f:
            for rec in b_audit.records:
                f.write(rec.model_dump_json() + "\n")

        print(
            f"[{branch_id}] {label:<50s} -> Good: {bm.get('good_output', 0)}/140 | "
            f"LeadTime: {bm.get('lead_time_ns', 0)/1e9:6.1f}s | "
            f"Lateness: {bm.get('lateness_ns', 0)/1e9:6.1f}s | "
            f"Downtime: {bm.get('downtime_ns', 0)/1e9:5.1f}s | "
            f"Batches: {len(summary.decision_batches):2d} | Cost: {summary.total_strategic_cost:6.2f}"
        )

    with open(output_base / "branch_comparison.json", "w", encoding="utf-8") as f:
        json.dump(branch_results, f, indent=2)

    # Master report
    master_report = {
        "experiment_id": "EXP-0004",
        "description": "Large-Scale Multi-Horizon, Multi-Seed Forecasting and Closed-Loop Decision Benchmark",
        "seeds": list(seeds),
        "horizons": list(horizons),
        "seed_simulations": seed_simulation_summaries,
        "forecasting_benchmark": aggregated_benchmark,
        "counterfactual_branches": branch_results,
    }
    with open(output_base / "large_scale_benchmark_report.json", "w", encoding="utf-8") as f:
        json.dump(master_report, f, indent=2)

    print("\n" + "=" * 90)
    print("EXP-0004 Benchmark Execution Complete!")
    print(f"Full report written to: {output_base / 'large_scale_benchmark_report.json'}")
    print("=" * 90 + "\n")

    return master_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Large-Scale Benchmark Suite")
    parser.add_argument("--config", type=str, default="examples/large_scale_benchmark_plant.yaml")
    parser.add_argument("--output-dir", type=str, default="runs/large_scale_benchmark")
    parser.add_argument("--seeds", type=str, default="42,101,2026")
    parser.add_argument("--horizons", type=str, default="8,16,32,64,128")
    parser.add_argument("--context-len", type=int, default=64)
    parser.add_argument("--stride", type=int, default=16)
    parser.add_argument("--checkpoint-time", type=float, default=240.0)
    args = parser.parse_args()

    seeds = tuple(int(s.strip()) for s in args.seeds.split(",") if s.strip())
    horizons = tuple(int(h.strip()) for h in args.horizons.split(",") if h.strip())

    run_benchmark(
        config_path=args.config,
        output_dir=args.output_dir,
        seeds=seeds,
        horizons=horizons,
        context_len=args.context_len,
        stride=args.stride,
        branch_checkpoint_time_s=args.checkpoint_time,
    )


if __name__ == "__main__":
    main()

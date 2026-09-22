from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any
import numpy as np

from industrialsim.application import (
    EpisodeSummary,
    run_episode,
    validate_config,
)
from industrialsim.forecasting.baselines import MovingAverageForecaster
from industrialsim.forecasting.provider import PredictiveDecisionProvider
from industrialsim.forecasting.timesfm_adapter import TimesFM3Adapter

logger = logging.getLogger(__name__)


def run_counterfactual_experiment(
    config_path: str | Path = "examples/forecasting_benchmark_plant.yaml",
    output_dir: str | Path = "./runs/forecasting_eval/branch_comparison",
) -> dict[str, Any]:
    """
    Run comparative counterfactual episodes with identical seeds and Philox streams:
    - Branch 1: Baseline Reactive Heuristic (no proactive model)
    - Branch 2: TimesFM 3 Predictive Decision Provider
    - Branch 3: Moving Average Baseline Decision Provider
    """
    out_base = Path(output_dir)
    out_base.mkdir(parents=True, exist_ok=True)

    validation = validate_config(config_path)
    if not validation.is_valid or validation.config is None:
        raise ValueError(f"Invalid configuration {config_path}: {validation.errors}")
    cfg = validation.config

    # Extract production plan entries for future covariates
    plan_entries = [p.model_dump() for p in cfg.production_plan]

    # Setup providers
    timesfm_forecaster = TimesFM3Adapter(patch_len=32)
    timesfm_provider = PredictiveDecisionProvider(
        forecaster=timesfm_forecaster,
        provider_id="provider-timesfm3",
        model_id="timesfm-3.0",
        future_plan_entries=plan_entries,
        maintenance_risk_threshold=0.60,
    )

    ma_forecaster = MovingAverageForecaster(window_size=16)
    ma_provider = PredictiveDecisionProvider(
        forecaster=ma_forecaster,
        provider_id="provider-moving-avg",
        model_id="moving-average-baseline",
        future_plan_entries=plan_entries,
        maintenance_risk_threshold=0.60,
    )

    branches_config = [
        ("Branch_A_Reactive_Baseline", None, out_base / "branch_reactive"),
        ("Branch_B_TimesFM3_Predictive", timesfm_provider, out_base / "branch_timesfm3"),
        ("Branch_C_MovingAverage_Baseline", ma_provider, out_base / "branch_moving_avg"),
    ]

    results: dict[str, Any] = {}

    for branch_name, provider, branch_dir in branches_config:
        logger.info("Running simulation for %s...", branch_name)
        summary = run_episode(
            source=config_path,
            decision_provider=provider,
            output_dir=branch_dir,
        )

        lead_times = [
            u.history[-1]["time_ns"] - u.history[0]["time_ns"]
            for u in summary.production_units
            if u.state in ("terminal", "scrapped") and len(u.history) >= 2
        ]
        avg_lead_time_s = float(np.mean(lead_times) / 1e9) if lead_times else 0.0

        # Calculate metrics
        results[branch_name] = {
            "status": summary.status,
            "events_processed": summary.events_processed,
            "simulated_time_s": summary.simulated_time_ns / 1e9,
            "good_output": summary.raw_metrics.get("good_output", 0),
            "scrap": summary.raw_metrics.get("scrap", 0),
            "wip": summary.raw_metrics.get("wip", 0),
            "downtime_s": summary.raw_metrics.get("downtime_ns", 0) / 1e9,
            "lateness_s": summary.raw_metrics.get("lateness_ns", 0) / 1e9,
            "average_lead_time_s": avg_lead_time_s,
            "result_hash": summary.result_hash,
        }

    comparison_report = {
        "config_path": str(config_path),
        "seed": cfg.seed,
        "branches": results,
    }

    report_file = out_base / "counterfactual_comparison_report.json"
    report_file.write_text(json.dumps(comparison_report, indent=2), encoding="utf-8")
    return comparison_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Counterfactual Branching Experiment")
    parser.add_argument("--config", type=str, default="examples/forecasting_benchmark_plant.yaml", help="Plant config")
    parser.add_argument("--output-dir", type=str, default="./runs/forecasting_eval/branch_comparison", help="Output dir")
    args = parser.parse_args()

    print(f"Running counterfactual policy experiment on {args.config}...")
    report = run_counterfactual_experiment(config_path=args.config, output_dir=args.output_dir)

    print("\n" + "=" * 90)
    print(f"{'Branch':<32} | {'Good Output':<11} | {'Downtime (s)':<12} | {'WIP':<6} | {'Avg Lead (s)':<12}")
    print("-" * 90)
    for branch_name, data in report["branches"].items():
        print(
            f"{branch_name:<32} | {data['good_output']:<11} | {data['downtime_s']:<12.1f} | {data['wip']:<6} | {data['average_lead_time_s']:<12.1f}"
        )
    print("=" * 90 + "\n")


if __name__ == "__main__":
    main()

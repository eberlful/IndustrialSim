from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Sequence
import numpy as np
import pyarrow.parquet as pq

from industrialsim.application import run_episode, validate_config
from industrialsim.forecasting.baselines import (
    LinearTrendCovariateForecaster,
    MovingAverageForecaster,
    NaiveLastValueForecaster,
)
from industrialsim.forecasting.metrics import evaluate_forecast
from industrialsim.forecasting.timesfm_adapter import TimesFM3Adapter

logger = logging.getLogger(__name__)


def load_telemetry_series(telemetry_dir: Path | str) -> dict[str, np.ndarray]:
    """Load and concatenate Parquet telemetry fragments into numpy arrays."""
    t_path = Path(telemetry_dir)
    parquet_files = sorted(t_path.glob("metrics_fragment_*.parquet"))
    if not parquet_files:
        # Check parent dir or direct parquet file
        parquet_files = sorted(t_path.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet telemetry files found in {telemetry_dir}")

    tables = [pq.read_table(f) for f in parquet_files]
    import pyarrow as pa
    combined = pa.concat_tables(tables)
    pydict = combined.to_pydict()

    # Sort by simulated_time_ns
    order = np.argsort(pydict["simulated_time_ns"])
    series_dict: dict[str, np.ndarray] = {}
    for col_name, col_data in pydict.items():
        arr = np.asarray(col_data)[order]
        # Store numeric columns
        if np.issubdtype(arr.dtype, np.number):
            series_dict[col_name] = arr.astype(np.float64)

    return series_dict


def run_offline_benchmark(
    telemetry_dir: Path | str,
    context_len: int = 64,
    horizon: int = 32,
    stride: int = 16,
    target_names: Sequence[str] = ("wip", "good_output", "machines_busy", "downtime_ns"),
    covariate_names: Sequence[str] = ("scrap", "workers_busy", "vehicles_busy"),
) -> dict[str, Any]:
    """
    Run rolling-window forecasting evaluation comparing:
    1. TimesFM 3 (Multivariate with Past-Future Covariates)
    2. TimesFM 3 (Univariate mode)
    3. Linear Trend Covariate Baseline
    4. Moving Average Baseline
    5. Naive Last Value Persistence
    """
    series_data = load_telemetry_series(telemetry_dir)
    total_steps = len(next(iter(series_data.values())))

    min_required = context_len + horizon
    if total_steps < min_required:
        raise ValueError(f"Telemetry series length ({total_steps}) is shorter than context + horizon ({min_required})")

    models = {
        "TimesFM-3 (Multivariate)": TimesFM3Adapter(patch_len=32),
        "TimesFM-3 (Univariate)": TimesFM3Adapter(patch_len=32),
        "Linear Trend + Covariates": LinearTrendCovariateForecaster(),
        "Moving Average (w=16)": MovingAverageForecaster(window_size=16),
        "Naive Persistence": NaiveLastValueForecaster(),
    }

    eval_results: dict[str, list[dict[str, dict[str, float]]]] = {m: [] for m in models}

    # Rolling evaluation windows
    window_starts = list(range(0, total_steps - min_required + 1, stride))

    for start in window_starts:
        ctx_end = start + context_len
        horiz_end = ctx_end + horizon

        past_targets = {
            t: series_data[t][start:ctx_end]
            for t in target_names
            if t in series_data
        }
        actual_future = {
            t: series_data[t][ctx_end:horiz_end]
            for t in target_names
            if t in series_data
        }
        past_covs = {
            c: series_data[c][start:ctx_end]
            for c in covariate_names
            if c in series_data
        }
        # Future covariates: known future values from telemetry (simulating known plan)
        future_covs = {
            c: series_data[c][ctx_end:horiz_end]
            for c in covariate_names
            if c in series_data
        }

        for model_name, model in models.items():
            if model_name == "TimesFM-3 (Univariate)":
                # Ablation: no covariates passed
                forecast = model.forecast(
                    past_targets=past_targets,
                    past_covariates=None,
                    future_covariates=None,
                    horizon=horizon,
                )
            else:
                forecast = model.forecast(
                    past_targets=past_targets,
                    past_covariates=past_covs,
                    future_covariates=future_covs,
                    horizon=horizon,
                )

            metrics = evaluate_forecast(actual_future, forecast)
            eval_results[model_name].append(metrics)

    # Aggregate across rolling windows
    summary: dict[str, Any] = {
        "context_len": context_len,
        "horizon": horizon,
        "num_windows": len(window_starts),
        "targets_evaluated": list(target_names),
        "models": {},
    }

    for model_name, window_metrics_list in eval_results.items():
        model_summary: dict[str, dict[str, float]] = {}
        for target in target_names:
            target_metric_keys = ["mae", "rmse", "wape", "crps", "mean_wql", "wql_q50", "wql_q90"]
            agg: dict[str, float] = {}
            for k in target_metric_keys:
                vals = [w[target][k] for w in window_metrics_list if target in w and k in w[target]]
                if vals:
                    agg[k] = float(np.mean(vals))
            model_summary[target] = agg

        # Overall average score across all targets
        overall_mae = float(np.mean([m.get("mae", 0.0) for m in model_summary.values()]))
        overall_rmse = float(np.mean([m.get("rmse", 0.0) for m in model_summary.values()]))
        overall_wape = float(np.mean([m.get("wape", 0.0) for m in model_summary.values()]))
        overall_crps = float(np.mean([m.get("crps", 0.0) for m in model_summary.values()]))
        overall_wql = float(np.mean([m.get("mean_wql", 0.0) for m in model_summary.values()]))

        summary["models"][model_name] = {
            "overall": {
                "mae": overall_mae,
                "rmse": overall_rmse,
                "wape": overall_wape,
                "crps": overall_crps,
                "mean_wql": overall_wql,
            },
            "by_target": model_summary,
        }

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Time-Series Forecasting Benchmark")
    parser.add_argument("--config", type=str, default=None, help="Plant config to generate telemetry first")
    parser.add_argument("--telemetry-dir", type=str, default=None, help="Directory containing parquet telemetry")
    parser.add_argument("--output-dir", type=str, default="./runs/forecasting_eval", help="Output directory")
    parser.add_argument("--output-report", type=str, default=None, help="Path to write JSON benchmark report")
    parser.add_argument("--generate-telemetry", action="store_true", help="Generate telemetry by running episode")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.generate_telemetry or args.config is not None:
        cfg_path = args.config or "examples/forecasting_benchmark_plant.yaml"
        print(f"Generating telemetry from {cfg_path}...")
        run_episode(cfg_path, output_dir=out_dir)
        telemetry_dir = out_dir / "telemetry"
    else:
        if args.telemetry_dir is None:
            raise ValueError("Either --config / --generate-telemetry or --telemetry-dir must be provided.")
        telemetry_dir = Path(args.telemetry_dir)

    print(f"Running offline benchmark on {telemetry_dir}...")
    report = run_offline_benchmark(telemetry_dir=telemetry_dir)

    report_path = Path(args.output_report) if args.output_report else (out_dir / "offline_benchmark_report.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report written to {report_path}")

    # Print summary table
    print("\n" + "=" * 80)
    print(f"{'Model':<30} | {'MAE':<10} | {'RMSE':<10} | {'WAPE':<10} | {'CRPS':<10} | {'Mean WQL':<10}")
    print("-" * 80)
    for model_name, res in report["models"].items():
        ov = res["overall"]
        print(
            f"{model_name:<30} | {ov['mae']:<10.3f} | {ov['rmse']:<10.3f} | {ov['wape']:<10.3f} | {ov['crps']:<10.3f} | {ov['mean_wql']:<10.3f}"
        )
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from pathlib import Path
import pytest

from industrialsim.benchmark import (
    collect_hardware_metadata,
    run_scheduler_benchmark,
    run_reference_plant_benchmark,
    run_benchmark,
    BenchmarkReport,
    SchedulerBenchmarkResult,
    PlantBenchmarkResult,
)


def test_collect_hardware_metadata() -> None:
    hw = collect_hardware_metadata()
    assert isinstance(hw, dict)
    assert "cpu_count" in hw
    assert "architecture" in hw
    assert "processor" in hw
    assert "documented_reference_hardware" in hw
    ref = hw["documented_reference_hardware"]
    assert "target_scheduler_events" in ref
    assert ref["target_scheduler_events"] == 5_000_000
    assert "target_scheduler_max_seconds" in ref
    assert ref["target_scheduler_max_seconds"] == 60.0
    assert ref["target_plant_min_resources"] == 100
    assert ref["target_plant_max_resources"] == 500


def test_run_scheduler_benchmark_determinism_and_performance() -> None:
    # Run with 100_000 for quick unit test verification
    res = run_scheduler_benchmark(events=100_000, repetitions=2)
    assert isinstance(res, SchedulerBenchmarkResult)
    assert res.target == "scheduler"
    assert res.events_processed == 100_000
    assert res.duration_seconds < 60.0
    assert res.is_deterministic is True
    assert res.status == "passed"
    assert len(res.repetitions) == 2
    assert res.repetitions[0]["result_hash"] == res.repetitions[1]["result_hash"]
    assert "timing" in res.to_dict()
    assert "workload" in res.to_dict()


def test_run_reference_plant_benchmark_scale_and_determinism() -> None:
    res = run_reference_plant_benchmark(events=10_000, repetitions=2)
    assert isinstance(res, PlantBenchmarkResult)
    assert res.target == "reference_plant"
    assert 100 <= res.active_resources <= 500
    assert res.production_week_simulated_time_ns == 432_000_000_000_000  # 5 days
    assert res.duration_seconds < 60.0
    assert res.is_deterministic is True
    assert res.status == "passed"
    assert len(res.repetitions) == 2
    assert res.repetitions[0]["result_hash"] == res.repetitions[1]["result_hash"]
    assert "timing" in res.to_dict()
    assert "workload" in res.to_dict()
    assert "resource_breakdown" in res.to_dict()


def test_run_benchmark_unified_report(tmp_path: Path) -> None:
    out_dir = tmp_path / "bench_out"
    report = run_benchmark(
        target="all",
        scheduler_events=10_000,
        plant_events=5_000,
        repetitions=2,
        output_dir=out_dir,
    )
    assert isinstance(report, BenchmarkReport)
    assert report.status == "passed"
    assert report.scheduler is not None
    assert report.plant is not None
    assert report.runtime is not None
    assert report.hardware is not None

    report_file = out_dir / "benchmark_report.json"
    assert report_file.exists()
    data = json.loads(report_file.read_text(encoding="utf-8"))
    assert data["status"] == "passed"
    assert "timing" in data["scheduler"]
    assert "hardware" in data
    assert "runtime" in data

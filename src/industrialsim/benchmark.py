from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import time
from typing import Any, Sequence

from industrialsim.audit import collect_library_metadata, collect_runtime_metadata
from industrialsim.application import run_episode, validate_config, EpisodeSummary
from industrialsim.kernel import EventKernel, EventPriority, ScheduledEvent


def collect_hardware_metadata() -> dict[str, Any]:
    cpu_count = os.cpu_count() or 1
    processor = platform.processor() or platform.machine()
    architecture = platform.machine()
    cpu_model = "unknown"
    total_memory_bytes: int | None = None

    try:
        cpuinfo_p = Path("/proc/cpuinfo")
        if cpuinfo_p.exists():
            for line in cpuinfo_p.read_text(encoding="utf-8").splitlines():
                if "model name" in line:
                    cpu_model = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass

    try:
        meminfo_p = Path("/proc/meminfo")
        if meminfo_p.exists():
            for line in meminfo_p.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    kb_val = int(line.split(":")[1].replace("kB", "").strip())
                    total_memory_bytes = kb_val * 1024
                    break
    except Exception:
        pass

    if total_memory_bytes is None:
        try:
            total_memory_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except Exception:
            pass

    return {
        "architecture": architecture,
        "processor": processor,
        "cpu_model": cpu_model if cpu_model != "unknown" else processor,
        "cpu_count": cpu_count,
        "total_memory_bytes": total_memory_bytes,
        "documented_reference_hardware": {
            "baseline_description": "Standard modern multicore CPU (x86_64/ARM64, >= 2.4 GHz, 8+ cores), 16+ GB RAM, CPython 3.12",
            "target_scheduler_events": 5_000_000,
            "target_scheduler_max_seconds": 60.0,
            "target_plant_min_resources": 100,
            "target_plant_max_resources": 500,
            "target_plant_events": 100_000,
            "target_plant_max_seconds": 60.0,
        },
    }


@dataclass(frozen=True)
class BaseBenchmarkResult:
    target: str
    events_processed: int
    duration_seconds: float
    events_per_second: float
    repetitions: list[dict[str, Any]]
    is_deterministic: bool
    status: str
    timing: dict[str, Any]
    workload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "events_processed": self.events_processed,
            "duration_seconds": self.duration_seconds,
            "events_per_second": self.events_per_second,
            "repetitions": list(self.repetitions),
            "is_deterministic": self.is_deterministic,
            "status": self.status,
            "timing": dict(self.timing),
            "workload": dict(self.workload),
        }


@dataclass(frozen=True)
class SchedulerBenchmarkResult(BaseBenchmarkResult):
    pass


@dataclass(frozen=True)
class PlantBenchmarkResult(BaseBenchmarkResult):
    active_resources: int = 0
    resource_breakdown: dict[str, int] = field(default_factory=dict)
    production_week_simulated_time_ns: int = 0

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "active_resources": self.active_resources,
            "resource_breakdown": dict(self.resource_breakdown),
            "production_week_simulated_time_ns": self.production_week_simulated_time_ns,
        })
        return base


@dataclass(frozen=True)
class BenchmarkReport:
    status: str
    timestamp: str
    runtime: dict[str, Any]
    hardware: dict[str, Any]
    scheduler: SchedulerBenchmarkResult | None = None
    plant: PlantBenchmarkResult | None = None

    @property
    def kernel(self) -> SchedulerBenchmarkResult | None:
        """Domain alias for discrete-event engine benchmark (EventKernel)."""
        return self.scheduler

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "timestamp": self.timestamp,
            "runtime": dict(self.runtime),
            "hardware": dict(self.hardware),
            "scheduler": self.scheduler.to_dict() if self.scheduler is not None else None,
            "kernel": self.scheduler.to_dict() if self.scheduler is not None else None,
            "plant": self.plant.to_dict() if self.plant is not None else None,
        }


def _evaluate_benchmark_repetitions(
    reps_data: list[dict[str, Any]],
    workload: dict[str, Any],
    additional_pass_condition: bool = True,
    max_duration_seconds: float = 60.0,
) -> tuple[bool, str, dict[str, Any], dict[str, Any]]:
    is_deterministic = len(set(r["result_hash"] for r in reps_data)) == 1
    first = reps_data[0]
    total_duration = first["duration_seconds"]
    total_cpu = first["cpu_time_seconds"]
    events_proc = first["events_processed"]
    ev_per_sec = first["events_per_second"]

    passed = (
        is_deterministic
        and additional_pass_condition
        and total_duration <= max_duration_seconds
    )

    timing = {
        "duration_seconds": total_duration,
        "cpu_time_seconds": total_cpu,
        "events_per_second": ev_per_sec,
        "event_latency_ns": (total_duration / events_proc) * 1e9 if events_proc > 0 else 0.0,
    }
    status = "passed" if passed else "failed"
    return is_deterministic, status, timing, workload


def run_scheduler_benchmark(events: int = 5_000_000, repetitions: int = 2) -> SchedulerBenchmarkResult:
    reps_data: list[dict[str, Any]] = []

    # Single-threaded sequential baseline
    num_chains = min(1000, events)
    steps_per_chain = events // num_chains
    remainder = events % num_chains

    for rep in range(max(1, repetitions)):
        kernel = EventKernel(initial_time_ns=0)
        h = hashlib.sha256()

        def handler(k: EventKernel, ev: ScheduledEvent) -> None:
            max_steps = ev.payload["max_steps"]
            step = ev.payload["step"]
            h.update(f"{ev.time_ns}:{ev.sequence}:{ev.payload['id']}:{step};".encode("ascii"))
            if step + 1 < max_steps:
                k.schedule(
                    ev.time_ns + 1000,
                    EventPriority.COMPLETION,
                    "BENCH_EVENT",
                    {"id": ev.payload["id"], "step": step + 1, "max_steps": max_steps},
                )

        kernel.register_handler("BENCH_EVENT", handler)

        t_start = time.perf_counter()
        c_start = time.process_time()

        for i in range(num_chains):
            extra = 1 if i < remainder else 0
            kernel.schedule(
                i * 10,
                EventPriority.COMPLETION,
                "BENCH_EVENT",
                {"id": i, "step": 0, "max_steps": steps_per_chain + extra},
            )

        processed = kernel.run_until_empty()
        t_end = time.perf_counter()
        c_end = time.process_time()

        duration = max(t_end - t_start, 1e-9)
        cpu_duration = max(c_end - c_start, 1e-9)
        res_hash = h.hexdigest()

        reps_data.append({
            "repetition": rep + 1,
            "events_processed": processed,
            "duration_seconds": duration,
            "cpu_time_seconds": cpu_duration,
            "events_per_second": processed / duration,
            "result_hash": res_hash,
        })

    events_proc = reps_data[0]["events_processed"]
    workload = {
        "target_events": events,
        "events_processed": events_proc,
        "repetitions": repetitions,
    }
    is_det, status, timing, workload = _evaluate_benchmark_repetitions(
        reps_data,
        workload=workload,
        additional_pass_condition=(events_proc == events),
        max_duration_seconds=60.0,
    )

    return SchedulerBenchmarkResult(
        target="scheduler",
        events_processed=events_proc,
        duration_seconds=timing["duration_seconds"],
        events_per_second=timing["events_per_second"],
        repetitions=reps_data,
        is_deterministic=is_det,
        status=status,
        timing=timing,
        workload=workload,
    )


def build_reference_plant_benchmark_config(units_count: int = 100) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    machines: list[dict[str, Any]] = []
    workers: list[dict[str, Any]] = []

    areas = [
        {
            "id": "area-body-construction",
            "name": "Body Construction Area",
            "halls": [{"id": "hall-body-construction", "name": "Body Construction Hall"}],
        },
        {
            "id": "area-paint-application",
            "name": "Paint Application Area",
            "halls": [{"id": "hall-paint-application", "name": "Paint Application Hall"}],
        },
        {
            "id": "area-final-assembly",
            "name": "Final Assembly Area",
            "halls": [{"id": "hall-final-assembly", "name": "Final Assembly Hall"}],
        },
    ]

    # 5 parallel production lines across Body, Paint, and Final Assembly
    # Each line has 10 stations and 10 buffers:
    # 0..2: Body Construction (3 stations, 3 buffers)
    # 3..5: Paint Application (3 stations, 3 buffers)
    # 6..9: Final Assembly (4 stations, 4 buffers)
    # 50 stations + 50 buffers = 100 material-flow nodes
    # 50 machines + 50 workers + 5 vehicles = 205 active resources (between 100 and 500)
    num_lines = 5
    stations_per_line = 10
    total_week_seconds = 5 * 24 * 3600  # 432,000s = 1 production week (120h)

    for line in range(num_lines):
        nodes.append({
            "id": f"src-{line}",
            "kind": "source",
            "hall_id": "hall-body-construction",
            "output_ports": [{"id": "p-out", "port_type": "body", "direction": "output"}],
        })
        prev_node = f"src-{line}"
        prev_port = "p-out"

        for st_idx in range(stations_per_line):
            if st_idx < 3:
                hall_id = "hall-body-construction"
                w_qual = "body_worker"
            elif st_idx < 6:
                hall_id = "hall-paint-application"
                w_qual = "paint_worker"
            else:
                hall_id = "hall-final-assembly"
                w_qual = "assembly_worker"

            buf_id = f"buf-{line}-{st_idx}"
            nodes.append({
                "id": buf_id,
                "kind": "buffer",
                "hall_id": hall_id,
                "capacity": 20,
                "input_ports": [{"id": "p-in", "port_type": "body", "direction": "input"}],
                "output_ports": [{"id": "p-out", "port_type": "body", "direction": "output"}],
            })
            routes.append({
                "id": f"r-{prev_node}-to-{buf_id}",
                "source_node_id": prev_node,
                "source_port_id": prev_port,
                "target_node_id": buf_id,
                "target_port_id": "p-in",
                "transit_time": "1s",
            })

            st_id = f"st-{line}-{st_idx}"
            m_id = f"m-{line}-{st_idx}"
            w_id = f"w-{line}-{st_idx}"
            machines.append({"id": m_id, "initial_health": 1.0})
            workers.append({
                "id": w_id,
                "qualifications": [w_qual],
                "shifts": [{"id": f"s-{w_id}", "start_time": "0s", "end_time": "5d"}],
            })
            nodes.append({
                "id": st_id,
                "kind": "station",
                "hall_id": hall_id,
                "operations": [{
                    "id": f"op-{line}-{st_idx}",
                    "duration": "2s",
                    "required_machines": [m_id],
                    "required_workers": [{"qualification": w_qual, "count": 1}],
                    "interruption_policy": "resume",
                }],
                "input_ports": [{"id": "p-in", "port_type": "body", "direction": "input"}],
                "output_ports": [{"id": "p-out", "port_type": "body", "direction": "output"}],
            })
            routes.append({
                "id": f"r-{buf_id}-to-{st_id}",
                "source_node_id": buf_id,
                "source_port_id": "p-out",
                "target_node_id": st_id,
                "target_port_id": "p-in",
                "transit_time": "1s",
            })
            prev_node = st_id
            prev_port = "p-out"

        nodes.append({
            "id": f"snk-{line}",
            "kind": "sink",
            "hall_id": "hall-final-assembly",
            "input_ports": [{"id": "p-in", "port_type": "body", "direction": "input"}],
        })
        routes.append({
            "id": f"r-{prev_node}-to-snk-{line}",
            "source_node_id": prev_node,
            "source_port_id": prev_port,
            "target_node_id": f"snk-{line}",
            "target_port_id": "p-in",
            "transit_time": "1s",
        })

    vehicles = [
        {"id": f"agv-{v}", "initial_location": f"buf-{v}-0"}
        for v in range(5)
    ]

    units_per_line = max(1, units_count // num_lines)
    units_plan: list[dict[str, Any]] = []
    for line in range(num_lines):
        for u in range(units_per_line):
            variant = "sedan" if (line + u) % 2 == 0 else "suv"
            release_s = int((u / units_per_line) * (total_week_seconds - 3600)) if units_per_line > 1 else 0
            units_plan.append({
                "id": f"u-{line}-{u}",
                "variant": variant,
                "release_time": f"{release_s}s",
                "due_date": f"{release_s + 7200}s",
                "source_id": f"src-{line}",
            })

    return {
        "schema_version": "1.0",
        "seed": 42,
        "plant": {
            "id": "plant-reference-automotive-benchmark",
            "name": "Reference Automotive Plant Benchmark",
            "areas": areas,
        },
        "episode": {
            "start_time": "0s",
            "end_condition": {"type": "max_time", "max_time": "5d"},  # 1 production week (120 hours)
        },
        "material_flow": {
            "nodes": nodes,
            "routes": routes,
        },
        "machines": machines,
        "workers": workers,
        "vehicles": vehicles,
        "production_plan": units_plan,
    }


def run_reference_plant_benchmark(events: int = 100_000, repetitions: int = 2) -> PlantBenchmarkResult:
    # Estimate units needed to achieve target events (~32 events per unit in 10-station line)
    units_target = max(20, events // 30)
    cfg_dict = build_reference_plant_benchmark_config(units_count=units_target)

    num_stations = len([n for n in cfg_dict["material_flow"]["nodes"] if n.get("kind") == "station"])
    num_buffers = len([n for n in cfg_dict["material_flow"]["nodes"] if n.get("kind") == "buffer"])
    num_machines = len(cfg_dict.get("machines", []))
    num_workers = len(cfg_dict.get("workers", []))
    num_vehicles = len(cfg_dict.get("vehicles", []))
    active_resources = num_stations + num_buffers + num_machines + num_workers + num_vehicles

    resource_breakdown = {
        "stations": num_stations,
        "buffers": num_buffers,
        "machines": num_machines,
        "workers": num_workers,
        "vehicles": num_vehicles,
        "total_active_resources": active_resources,
    }

    reps_data: list[dict[str, Any]] = []

    for rep in range(max(1, repetitions)):
        t_start = time.perf_counter()
        c_start = time.process_time()

        # Run single-threaded single branch
        summary = run_episode(cfg_dict)

        t_end = time.perf_counter()
        c_end = time.process_time()

        duration = max(t_end - t_start, 1e-9)
        cpu_duration = max(c_end - c_start, 1e-9)

        reps_data.append({
            "repetition": rep + 1,
            "events_processed": summary.events_processed,
            "duration_seconds": duration,
            "cpu_time_seconds": cpu_duration,
            "events_per_second": summary.events_processed / duration,
            "result_hash": summary.result_hash,
            "simulated_time_ns": summary.simulated_time_ns,
        })

    events_proc = reps_data[0]["events_processed"]
    sim_time_ns = reps_data[0]["simulated_time_ns"]
    workload = {
        "active_resources": active_resources,
        "events_processed": events_proc,
        "simulated_time_ns": sim_time_ns,
        "production_units": len(cfg_dict.get("production_plan", [])),
        "repetitions": repetitions,
    }
    is_det, status, timing, workload = _evaluate_benchmark_repetitions(
        reps_data,
        workload=workload,
        additional_pass_condition=(100 <= active_resources <= 500),
        max_duration_seconds=60.0,
    )

    return PlantBenchmarkResult(
        target="reference_plant",
        events_processed=events_proc,
        active_resources=active_resources,
        resource_breakdown=resource_breakdown,
        production_week_simulated_time_ns=sim_time_ns,
        duration_seconds=timing["duration_seconds"],
        events_per_second=timing["events_per_second"],
        repetitions=reps_data,
        is_deterministic=is_det,
        status=status,
        timing=timing,
        workload=workload,
    )


def run_benchmark(
    target: str = "all",
    scheduler_events: int = 5_000_000,
    plant_events: int = 100_000,
    repetitions: int = 2,
    output_dir: str | Path | None = None,
) -> BenchmarkReport:
    hw_metadata = collect_hardware_metadata()
    rt_metadata = {
        "runtime": collect_runtime_metadata(),
        "libraries": collect_library_metadata(),
    }

    sched_res: SchedulerBenchmarkResult | None = None
    plant_res: PlantBenchmarkResult | None = None

    if target in ("all", "scheduler", "kernel"):
        sched_res = run_scheduler_benchmark(events=scheduler_events, repetitions=repetitions)

    if target in ("all", "plant", "reference_plant"):
        plant_res = run_reference_plant_benchmark(events=plant_events, repetitions=repetitions)

    all_passed = True
    if sched_res is not None and sched_res.status != "passed":
        all_passed = False
    if plant_res is not None and plant_res.status != "passed":
        all_passed = False

    report = BenchmarkReport(
        status="passed" if all_passed else "failed",
        timestamp=datetime.now(timezone.utc).isoformat(),
        runtime=rt_metadata,
        hardware=hw_metadata,
        scheduler=sched_res,
        plant=plant_res,
    )

    if output_dir is not None:
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)
        (out_p / "benchmark_report.json").write_text(
            json.dumps(report.to_dict(), indent=2), encoding="utf-8"
        )

    return report


# Domain aliases (GLOSSARY.md specifies "Dispatch Policy: Avoid: Scheduler, Router";
# the discrete-event stepping engine is the EventKernel, while Issue 16 refers to it as "Scheduler benchmark").
KernelBenchmarkResult = SchedulerBenchmarkResult
run_kernel_benchmark = run_scheduler_benchmark


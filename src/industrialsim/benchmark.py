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
            "baseline_description": "Standard modern multicore CPU (x86_64/ARM64, >= 2.4 GHz, 8+ cores), 16+ GB RAM, CPython 3.14",
            "target_scheduler_events": 5_000_000,
            "target_scheduler_max_seconds": 60.0,
            "target_plant_min_resources": 100,
            "target_plant_max_resources": 500,
            "target_plant_events": 2_000_000,
            "target_plant_max_seconds": 60.0,
        },
    }


@dataclass(frozen=True)
class SchedulerBenchmarkResult:
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
class PlantBenchmarkResult:
    target: str
    events_processed: int
    active_resources: int
    resource_breakdown: dict[str, int]
    production_week_simulated_time_ns: int
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
            "active_resources": self.active_resources,
            "resource_breakdown": dict(self.resource_breakdown),
            "production_week_simulated_time_ns": self.production_week_simulated_time_ns,
            "duration_seconds": self.duration_seconds,
            "events_per_second": self.events_per_second,
            "repetitions": list(self.repetitions),
            "is_deterministic": self.is_deterministic,
            "status": self.status,
            "timing": dict(self.timing),
            "workload": dict(self.workload),
        }


@dataclass(frozen=True)
class BenchmarkReport:
    status: str
    timestamp: str
    runtime: dict[str, Any]
    hardware: dict[str, Any]
    scheduler: SchedulerBenchmarkResult | None = None
    plant: PlantBenchmarkResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "timestamp": self.timestamp,
            "runtime": dict(self.runtime),
            "hardware": dict(self.hardware),
            "scheduler": self.scheduler.to_dict() if self.scheduler is not None else None,
            "plant": self.plant.to_dict() if self.plant is not None else None,
        }


def run_scheduler_benchmark(events: int = 5_000_000, repetitions: int = 2) -> SchedulerBenchmarkResult:
    reps_data: list[dict[str, Any]] = []

    for rep in range(repetitions):
        kernel = EventKernel(initial_time_ns=0)
        h = hashlib.sha256()

        num_chains = min(10_000, max(1, events // 100))
        steps_per_chain = events // num_chains
        remainder = events % num_chains

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

    is_deterministic = len(set(r["result_hash"] for r in reps_data)) == 1
    total_duration = reps_data[0]["duration_seconds"]
    total_cpu = reps_data[0]["cpu_time_seconds"]
    events_proc = reps_data[0]["events_processed"]
    ev_per_sec = reps_data[0]["events_per_second"]

    passed = (
        is_deterministic
        and events_proc == events
        and total_duration <= 60.0
    )

    timing = {
        "duration_seconds": total_duration,
        "cpu_time_seconds": total_cpu,
        "events_per_second": ev_per_sec,
        "event_latency_ns": (total_duration / events_proc) * 1e9 if events_proc > 0 else 0.0,
    }
    workload = {
        "target_events": events,
        "events_processed": events_proc,
        "repetitions": repetitions,
    }

    return SchedulerBenchmarkResult(
        target="scheduler",
        events_processed=events_proc,
        duration_seconds=total_duration,
        events_per_second=ev_per_sec,
        repetitions=reps_data,
        is_deterministic=is_deterministic,
        status="passed" if passed else "failed",
        timing=timing,
        workload=workload,
    )


def build_reference_plant_benchmark_config(units_count: int = 100) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    machines: list[dict[str, Any]] = []
    workers: list[dict[str, Any]] = []

    # 5 parallel production lines across Body, Paint, and Final Assembly
    # Each line has 10 stations and 10 buffers
    # 5 * 10 = 50 stations
    # 5 * 10 = 50 buffers
    # 50 machines
    # 50 workers
    # 5 vehicles
    # Total active resources = 50 + 50 + 50 + 50 + 5 = 205 resources (between 100 and 500)
    num_lines = 5
    stations_per_line = 10

    for line in range(num_lines):
        nodes.append({
            "id": f"src-{line}",
            "kind": "source",
            "output_ports": [{"id": "p-out", "port_type": "body", "direction": "output"}],
        })
        prev_node = f"src-{line}"
        prev_port = "p-out"

        for st_idx in range(stations_per_line):
            buf_id = f"buf-{line}-{st_idx}"
            nodes.append({
                "id": buf_id,
                "kind": "buffer",
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
                "qualifications": ["automotive_operator"],
                "shifts": [{"id": f"s-{w_id}", "start_time": "0s", "end_time": "5d"}],
            })
            nodes.append({
                "id": st_id,
                "kind": "station",
                "operations": [{
                    "id": f"op-{line}-{st_idx}",
                    "duration": "2s",
                    "required_machines": [m_id],
                    "required_workers": [{"qualification": "automotive_operator", "count": 1}],
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
            units_plan.append({
                "id": f"u-{line}-{u}",
                "variant": "sedan",
                "release_time": f"{u * 10}s",
                "due_date": f"{u * 10 + 2000}s",
                "source_id": f"src-{line}",
            })

    return {
        "schema_version": "1.0",
        "seed": 42,
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


def run_reference_plant_benchmark(events: int = 10_000, repetitions: int = 2) -> PlantBenchmarkResult:
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
    }

    reps_data: list[dict[str, Any]] = []

    for rep in range(repetitions):
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

    is_deterministic = len(set(r["result_hash"] for r in reps_data)) == 1
    total_duration = reps_data[0]["duration_seconds"]
    total_cpu = reps_data[0]["cpu_time_seconds"]
    events_proc = reps_data[0]["events_processed"]
    ev_per_sec = reps_data[0]["events_per_second"]
    sim_time_ns = reps_data[0]["simulated_time_ns"]

    passed = (
        is_deterministic
        and 100 <= active_resources <= 500
        and total_duration <= 60.0
    )

    timing = {
        "duration_seconds": total_duration,
        "cpu_time_seconds": total_cpu,
        "events_per_second": ev_per_sec,
        "event_latency_ns": (total_duration / events_proc) * 1e9 if events_proc > 0 else 0.0,
    }
    workload = {
        "active_resources": active_resources,
        "events_processed": events_proc,
        "simulated_time_ns": sim_time_ns,
        "production_units": len(cfg_dict.get("production_plan", [])),
        "repetitions": repetitions,
    }

    return PlantBenchmarkResult(
        target="reference_plant",
        events_processed=events_proc,
        active_resources=active_resources,
        resource_breakdown=resource_breakdown,
        production_week_simulated_time_ns=sim_time_ns,
        duration_seconds=total_duration,
        events_per_second=ev_per_sec,
        repetitions=reps_data,
        is_deterministic=is_deterministic,
        status="passed" if passed else "failed",
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

    if target in ("all", "scheduler"):
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

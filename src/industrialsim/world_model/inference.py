"""Persistent JSONL worker using the simulator's project interpreter."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import selectors
from typing import Any, Sequence

from industrialsim.world_model.contracts import (CHANNELS, STEP_NS, PlantGraph, RolloutResult,
                                                StudyObservation, TimedAction, portable)


class ArtifactWorldModel:
    def __init__(self, model_path: Path, worker_path: Path, device: str = "cpu",
                 timeout_seconds: float = 60) -> None:
        self.timeout_seconds = timeout_seconds
        self.process = subprocess.Popen([sys.executable, str(worker_path), "serve", "--model",
            str(model_path), "--device", device], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1)

    def rollout(self, history: Sequence[StudyObservation], graph: PlantGraph,
                actions: Sequence[TimedAction], production_plan: Sequence[dict[str, Any]],
                horizon: int = 10) -> RolloutResult:
        if not history or not 1 <= horizon <= 10000:
            raise ValueError("Nonempty history and bounded positive horizon required")
        if len({(o.episode_id, o.branch_id) for o in history}) != 1:
            raise ValueError("Inference history crosses an episode/branch boundary")
        if any(b.time_ns <= a.time_ns for a, b in zip(history, history[1:])):
            raise ValueError("Inference history must be strictly chronological")
        if any(len(o.values) != len(graph.node_ids) for o in history):
            raise ValueError("Observation graph size mismatch")
        response = self._exchange({"history": [portable(o) for o in history[-32:]],
            "graph": portable(graph), "actions": [portable(a) for a in actions],
            "production_plan": list(production_plan), "horizon": horizon})
        return self._result(response["values"], response["provenance"], history[-1].time_ns, horizon)

    def rollout_many(self, history: Sequence[StudyObservation], graph: PlantGraph,
                     action_batches: Sequence[Sequence[TimedAction]],
                     production_plan: Sequence[dict[str, Any]], horizon: int = 10) -> tuple[RolloutResult, ...]:
        if not history or len({(o.episode_id, o.branch_id) for o in history}) != 1:
            raise ValueError("Nonempty history from a single episode and branch required")
        if not 1 <= horizon <= 10000 or any(len(o.values) != len(graph.node_ids) for o in history):
            raise ValueError("Invalid rollout shape")
        response = self._exchange({"history": [portable(o) for o in history[-32:]],
            "graph": portable(graph), "action_batches": [[portable(a) for a in batch] for batch in action_batches],
            "production_plan": list(production_plan), "horizon": horizon})
        return tuple(self._result(values, response["provenance"], history[-1].time_ns, horizon)
                     for values in response["batches"])

    def _exchange(self, request: dict[str, Any]) -> dict[str, Any]:
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(json.dumps(request, allow_nan=False) + "\n")
        self.process.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            if not selector.select(self.timeout_seconds):
                self.close()
                raise TimeoutError("World model inference timed out")
        response = json.loads(self.process.stdout.readline())
        if response["status"] != "ok":
            raise RuntimeError(response["error"])
        return response

    def _result(self, raw: Any, provenance: dict[str, Any], start_ns: int, horizon: int) -> RolloutResult:
        values = tuple(tuple(tuple(float(v) for v in row) for row in step) for step in raw)
        metrics = tuple({name: step[0][CHANNELS.index(name)] for name in
            ("good_output", "scrap", "wip", "lateness_ns", "downtime_ns", "total_strategic_cost")}
            for step in values)
        times = tuple(start_ns + (i + 1) * STEP_NS for i in range(horizon))
        return RolloutResult(times, values, metrics, provenance)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout):
            if stream is not None:
                stream.close()

    def __enter__(self) -> ArtifactWorldModel:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

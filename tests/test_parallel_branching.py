from __future__ import annotations

import json
from pathlib import Path
import pytest

from industrialsim.application import (
    create_checkpoint,
    branch_checkpoint,
    BranchComparisonResult,
    CounterfactualBranchResult,
)
from industrialsim.decisions import BufferReorderAction

BASE_DECISION_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

material_flow:
  nodes:
    - id: "src-0"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "conveyor"
          direction: "output"
    - id: "src-1"
      kind: "source"
      output_ports:
        - id: "p-out-a"
          port_type: "conveyor"
          direction: "output"
        - id: "p-out-b"
          port_type: "conveyor"
          direction: "output"
    - id: "st-1a"
      kind: "station"
      operations:
        - id: "op-a"
          duration: "2s"
      input_ports:
        - id: "p-in"
          port_type: "conveyor"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "conveyor"
          direction: "output"
    - id: "st-1b"
      kind: "station"
      operations:
        - id: "op-b"
          duration: "2s"
      input_ports:
        - id: "p-in"
          port_type: "conveyor"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "conveyor"
          direction: "output"
    - id: "buf-1"
      kind: "buffer"
      capacity: 5
      input_ports:
        - id: "p-in-a"
          port_type: "conveyor"
          direction: "input"
        - id: "p-in-b"
          port_type: "conveyor"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "conveyor"
          direction: "output"
    - id: "st-2"
      kind: "station"
      operations:
        - id: "op-slow"
          duration: "5s"
      input_ports:
        - id: "p-in-0"
          port_type: "conveyor"
          direction: "input"
        - id: "p-in-buf"
          port_type: "conveyor"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "conveyor"
          direction: "output"
    - id: "snk-1"
      kind: "sink"
      input_ports:
        - id: "p-in"
          port_type: "conveyor"
          direction: "input"
  routes:
    - id: "r-src0-st2"
      source_node_id: "src-0"
      source_port_id: "p-out"
      target_node_id: "st-2"
      target_port_id: "p-in-0"
      transit_time: "0s"
    - id: "r-src1-st1a"
      source_node_id: "src-1"
      source_port_id: "p-out-a"
      target_node_id: "st-1a"
      target_port_id: "p-in"
      transit_time: "0s"
    - id: "r-src1-st1b"
      source_node_id: "src-1"
      source_port_id: "p-out-b"
      target_node_id: "st-1b"
      target_port_id: "p-in"
      transit_time: "0s"
    - id: "r-st1a-buf"
      source_node_id: "st-1a"
      source_port_id: "p-out"
      target_node_id: "buf-1"
      target_port_id: "p-in-a"
      transit_time: "0s"
    - id: "r-st1b-buf"
      source_node_id: "st-1b"
      source_port_id: "p-out"
      target_node_id: "buf-1"
      target_port_id: "p-in-b"
      transit_time: "0s"
    - id: "r-buf-st2"
      source_node_id: "buf-1"
      source_port_id: "p-out"
      target_node_id: "st-2"
      target_port_id: "p-in-buf"
      transit_time: "0s"
    - id: "r-st2-snk"
      source_node_id: "st-2"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"
      transit_time: "0s"

production_units:
  - id: "u-0"
    source_id: "src-0"
    variant: "v0"
    release_time: "0s"
  - id: "u-1"
    source_id: "src-1"
    variant: "sedan"
    release_time: "0s"
    due_date: "12s"
  - id: "u-2"
    source_id: "src-1"
    variant: "sedan"
    release_time: "0s"
    due_date: "12s"

decision_triggers:
  - id: "trig-buf-1"
    buffer_id: "buf-1"
    threshold: 2
    direction: "rising"
"""


def test_parallel_branch_execution_matches_sequential(tmp_path: Path) -> None:
    cp = create_checkpoint(BASE_DECISION_YAML, pause_at_decision_batch=True)

    action_1 = [BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-2"])]
    action_2 = [BufferReorderAction(target_id="buf-1", new_order=["u-2", "u-1"])]

    # Run sequentially (workers=1) and in parallel worker processes (workers=2)
    seq_dir = tmp_path / "seq"
    par_dir = tmp_path / "par"

    comp_seq = branch_checkpoint(cp, [action_1, action_2], output_dir=seq_dir, workers=1)
    comp_par = branch_checkpoint(cp, [action_1, action_2], output_dir=par_dir, workers=2)

    assert isinstance(comp_par, BranchComparisonResult)
    assert len(comp_par.branches) == 2

    # Verify identical hashes and summaries
    assert comp_seq.branches[0].result_hash == comp_par.branches[0].result_hash
    assert comp_seq.branches[1].result_hash == comp_par.branches[1].result_hash
    assert comp_seq.branches[0].status == "completed"
    assert comp_par.branches[0].status == "completed"
    assert comp_seq.to_dict() == comp_par.to_dict()

    # Verify artifacts written in both directories match
    seq_manifest = json.loads((seq_dir / "manifest.json").read_text(encoding="utf-8"))
    par_manifest = json.loads((par_dir / "manifest.json").read_text(encoding="utf-8"))
    assert seq_manifest["decision_batch_id"] == par_manifest["decision_batch_id"]
    assert len(seq_manifest["branches"]) == len(par_manifest["branches"])


def test_parallel_branch_worker_failure_is_structured_and_preserves_siblings() -> None:
    cp = create_checkpoint(BASE_DECISION_YAML, pause_at_decision_batch=True)

    action_valid = [BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-2"])]
    # An action payload that raises an execution error inside the branch worker:
    action_failing = {"__inject_worker_failure__": True}

    comp = branch_checkpoint(cp, [action_failing, action_valid], workers=2)

    assert len(comp.branches) == 2

    failed_branch = comp.branches[0]
    assert failed_branch.status == "failed"
    assert failed_branch.error is not None
    assert failed_branch.summary is None
    assert failed_branch.hard_constraints["satisfied"] is False
    assert failed_branch.hard_constraints["aborted"] is True

    successful_branch = comp.branches[1]
    assert successful_branch.status == "completed"
    assert successful_branch.error is None
    assert successful_branch.summary is not None
    assert successful_branch.result_hash != ""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from industrialsim.application import (
    create_checkpoint,
    save_checkpoint,
    load_checkpoint,
    branch_checkpoint,
    BranchComparisonResult,
    CounterfactualBranchResult,
    EpisodeEngine,
    run_episode,
)
from industrialsim.decisions import (
    BufferReorderAction,
    DecisionAction,
    DecisionBatchResponse,
    DecisionProvenance,
)

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
    on_failure: "fallback"
    fallback_policy: "fifo"
"""


def test_branch_at_least_two_alternatives_required() -> None:
    cp = create_checkpoint(BASE_DECISION_YAML, pause_at_decision_batch=True)
    assert cp.simulated_time_ns == 2_000_000_000

    # 0 alternatives
    with pytest.raises(ValueError, match="at least two"):
        branch_checkpoint(cp, [])

    # 1 alternative
    action_1 = [BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-2"])]
    with pytest.raises(ValueError, match="at least two"):
        branch_checkpoint(cp, [action_1])


def test_branch_rejects_non_decision_checkpoint() -> None:
    # An uninterrupted completed run has no pending decisions
    summary = run_episode(BASE_DECISION_YAML)
    assert summary.status == "completed"

    # A checkpoint at the very end of simulation
    cp = create_checkpoint(BASE_DECISION_YAML, at_time_ns=15_000_000_000)
    action_1 = [BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-2"])]
    action_2 = [BufferReorderAction(target_id="buf-1", new_order=["u-2", "u-1"])]

    with pytest.raises(ValueError, match="Decision Batch"):
        branch_checkpoint(cp, [action_1, action_2])


def test_branch_deterministic_identity() -> None:
    cp = create_checkpoint(BASE_DECISION_YAML, pause_at_decision_batch=True)

    action_1 = [BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-2"])]
    action_2 = [BufferReorderAction(target_id="buf-1", new_order=["u-2", "u-1"])]

    comp1 = branch_checkpoint(cp, [action_1, action_2])
    comp2 = branch_checkpoint(cp, [action_1, action_2])

    # Branch identities must be deterministic and identical on repetition
    assert len(comp1.branches) == 2
    assert len(comp2.branches) == 2
    assert comp1.branches[0].branch_id == comp2.branches[0].branch_id
    assert comp1.branches[1].branch_id == comp2.branches[1].branch_id

    # The two distinct action sets must have distinct branch_ids
    assert comp1.branches[0].branch_id != comp1.branches[1].branch_id


def test_branch_state_isolation() -> None:
    cp = create_checkpoint(BASE_DECISION_YAML, pause_at_decision_batch=True)
    orig_counters = dict(cp.random_occurrence_counters)

    action_1 = [BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-2"])]
    action_2 = [BufferReorderAction(target_id="buf-1", new_order=["u-2", "u-1"])]

    comp = branch_checkpoint(cp, [action_1, action_2])

    # Checkpoint occurrence counters and domain state should remain unmutated
    assert cp.random_occurrence_counters == orig_counters
    assert cp.domain_state["buffers"]["buf-1"].occupants == ["u-1", "u-2"]

    assert comp.branches[0].summary is not None
    assert comp.branches[1].summary is not None

    # In Branch 1 (FIFO order u-1, u-2):
    # u-1 exits st-2 first (at 10s), u-2 exits st-2 second (at 15s)
    b1_u1 = next(u for u in comp.branches[0].summary.production_units if u.id == "u-1")
    b1_u2 = next(u for u in comp.branches[0].summary.production_units if u.id == "u-2")
    assert b1_u1.history[-1]["time_ns"] < b1_u2.history[-1]["time_ns"]

    # In Branch 2 (Reverse order u-2, u-1):
    # u-2 exits st-2 first (at 10s), u-1 exits st-2 second (at 15s)
    b2_u1 = next(u for u in comp.branches[1].summary.production_units if u.id == "u-1")
    b2_u2 = next(u for u in comp.branches[1].summary.production_units if u.id == "u-2")
    assert b2_u2.history[-1]["time_ns"] < b2_u1.history[-1]["time_ns"]


def test_branch_sequential_repetition_determinism() -> None:
    cp = create_checkpoint(BASE_DECISION_YAML, pause_at_decision_batch=True)

    action_1 = [BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-2"])]
    action_2 = [BufferReorderAction(target_id="buf-1", new_order=["u-2", "u-1"])]

    # Run sequentially twice
    comp_a = branch_checkpoint(cp, [action_1, action_2])
    comp_b = branch_checkpoint(cp, [action_1, action_2])

    assert comp_a.branches[0].result_hash == comp_b.branches[0].result_hash
    assert comp_a.branches[1].result_hash == comp_b.branches[1].result_hash
    assert comp_a.to_dict() == comp_b.to_dict()


def test_branch_comparison_reports_metrics_and_hard_constraints() -> None:
    cp = create_checkpoint(BASE_DECISION_YAML, pause_at_decision_batch=True)

    action_1 = [BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-2"])]
    action_2 = [BufferReorderAction(target_id="buf-1", new_order=["u-2", "u-1"])]

    result = branch_checkpoint(cp, [action_1, action_2])

    assert isinstance(result, BranchComparisonResult)
    assert len(result.branches) == 2

    for branch in result.branches:
        assert isinstance(branch, CounterfactualBranchResult)
        assert branch.branch_id.startswith("branch-")
        assert len(branch.actions) == 1
        assert "provenance" in branch.to_dict()
        assert isinstance(branch.provenance, DecisionProvenance)
        assert branch.provenance.episode_id is not None
        assert branch.provenance.branch_id == branch.branch_id

        # Raw outcome metrics
        raw = branch.raw_metrics
        assert "good_output" in raw
        assert "lead_time_ns" in raw
        assert "wip" in raw
        assert "scrap" in raw
        assert "downtime_ns" in raw
        assert "lateness_ns" in raw
        assert "resource_utilization" in raw
        assert raw["good_output"] == 3
        assert raw["scrap"] == 0
        assert raw["wip"] == 0

        # Hard constraint outcomes
        hc = branch.hard_constraints
        assert "satisfied" in hc
        assert "violations" in hc
        assert "aborted" in hc
        assert hc["satisfied"] is True
        assert hc["aborted"] is False
        assert hc["violations"] == []

    # In branch 1 (FIFO): u-1 finishes at 10s (due 12s -> lateness 0), u-2 finishes at 15s (due 12s -> lateness 3s = 3_000_000_000 ns)
    assert result.branches[0].raw_metrics["lateness_ns"] == 3_000_000_000
    # In branch 2 (Reverse): u-2 finishes at 10s (due 12s -> lateness 0), u-1 finishes at 15s (due 12s -> lateness 3s = 3_000_000_000 ns)
    assert result.branches[1].raw_metrics["lateness_ns"] == 3_000_000_000


def test_action_set_order_invariance() -> None:
    from industrialsim.application import _derive_branch_id

    a1 = BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-2"])
    a2 = BufferReorderAction(target_id="buf-2", new_order=["u-3", "u-4"])

    # Permuting the order of actions inside an action set must yield the identical branch identity
    id_1 = _derive_branch_id(config_hash="abc", root_seed=42, simulated_time_ns=1000, actions=[a1, a2])
    id_2 = _derive_branch_id(config_hash="abc", root_seed=42, simulated_time_ns=1000, actions=[a2, a1])
    assert id_1 == id_2


def test_branch_provenance_preserves_provider_metadata() -> None:
    cp = create_checkpoint(BASE_DECISION_YAML, pause_at_decision_batch=True)

    resp_1 = DecisionBatchResponse(
        batch_id="batch-0001",
        provenance=DecisionProvenance(
            episode_id="ep-42",
            branch_id="main",
            batch_id="batch-0001",
            provider_id="custom-agent-v1",
            model_id="gemini-flash",
            prompt_id="prompt-123",
        ),
        actions=[BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-2"])],
    )
    resp_2 = DecisionBatchResponse(
        batch_id="batch-0001",
        provenance=DecisionProvenance(
            episode_id="ep-42",
            branch_id="main",
            batch_id="batch-0001",
            provider_id="baseline-rule",
            model_id="rule-engine",
            prompt_id="none",
        ),
        actions=[BufferReorderAction(target_id="buf-1", new_order=["u-2", "u-1"])],
    )

    comp = branch_checkpoint(cp, [resp_1, resp_2])
    b1 = comp.branches[0]
    b2 = comp.branches[1]

    assert b1.provenance.provider_id == "custom-agent-v1"
    assert b1.provenance.model_id == "gemini-flash"
    assert b1.provenance.prompt_id == "prompt-123"

    assert b2.provenance.provider_id == "baseline-rule"
    assert b2.provenance.model_id == "rule-engine"
    assert b2.provenance.prompt_id == "none"


def test_branch_reports_applied_actions_on_fallback() -> None:
    cp = create_checkpoint(BASE_DECISION_YAML, pause_at_decision_batch=True)

    action_valid = [BufferReorderAction(target_id="buf-1", new_order=["u-2", "u-1"])]
    # Invalid action triggers FIFO fallback
    action_invalid = [BufferReorderAction(target_id="buf-1", new_order=["u-unknown", "u-1"])]

    comp = branch_checkpoint(cp, [action_valid, action_invalid])

    # Branch 1 applied valid action (reverse order: u-2, u-1)
    assert comp.branches[0].actions[0]["new_order"] == ["u-2", "u-1"]

    # Branch 2 fell back to FIFO: the reported applied action is FIFO order ["u-1", "u-2"]
    assert comp.branches[1].actions[0]["new_order"] == ["u-1", "u-2"]


def test_hard_constraint_outcome_on_abort() -> None:
    abort_yaml = BASE_DECISION_YAML.replace('on_failure: "fallback"', 'on_failure: "abort"')
    cp = create_checkpoint(abort_yaml, pause_at_decision_batch=True)

    # Valid action in alternative 1
    action_valid = [BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-2"])]
    # Invalid action in alternative 2 (referencing non-existent unit)
    action_invalid = [BufferReorderAction(target_id="buf-1", new_order=["u-invalid", "u-1"])]

    comp = branch_checkpoint(cp, [action_valid, action_invalid])

    assert comp.branches[0].hard_constraints["satisfied"] is True
    assert comp.branches[0].hard_constraints["aborted"] is False

    assert comp.branches[1].hard_constraints["satisfied"] is False
    assert comp.branches[1].hard_constraints["aborted"] is True
    assert len(comp.branches[1].hard_constraints["violations"]) > 0
    assert "u-invalid" in comp.branches[1].hard_constraints["abort_reason"]


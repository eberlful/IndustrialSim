import pytest
from industrialsim.application import (
    run_episode,
    create_checkpoint,
    continue_checkpoint,
)
from industrialsim.decisions import (
    DecisionProvider,
    DecisionBatch,
    DecisionBatchResponse,
    DecisionProvenance,
    BufferReorderAction,
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
  - id: "u-2"
    source_id: "src-1"
    variant: "sedan"
    release_time: "0s"

decision_triggers:
  - id: "trig-buf-1"
    buffer_id: "buf-1"
    threshold: 2
    direction: "rising"
    on_failure: "fallback"
    fallback_policy: "fifo"
"""


class ReverseOrderProvider(DecisionProvider):
    def __init__(self) -> None:
        self.batches_seen: list[DecisionBatch] = []

    def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
        self.batches_seen.append(batch)
        actions = []
        for req in batch.requests:
            occupant_ids = [occ.unit_id for occ in req.observation.occupants]
            # Reverse order: put the latest arrival first!
            actions.append(
                BufferReorderAction(
                    target_id=req.target_id,
                    new_order=list(reversed(occupant_ids)),
                )
            )
        return DecisionBatchResponse(
            batch_id=batch.batch_id,
            provenance=DecisionProvenance(
                episode_id=batch.episode_id,
                batch_id=batch.batch_id,
                provider_id="reverse-provider",
                model_id="rule-v1",
                prompt_id="prompt-reverse",
            ),
            actions=actions,
        )


def test_decision_provider_reorders_buffer_atomically() -> None:
    # 1. Run baseline without decision provider (fallback FIFO is triggered):
    baseline_summary = run_episode(BASE_DECISION_YAML)
    assert baseline_summary.status == "completed"
    assert len(baseline_summary.decision_batches) == 1
    assert baseline_summary.decision_batches[0]["status"] == "fallback"

    # In baseline (FIFO), u-1 finishes at 10s and u-2 finishes at 15s
    u1_base = next(u for u in baseline_summary.production_units if u.id == "u-1")
    u2_base = next(u for u in baseline_summary.production_units if u.id == "u-2")
    assert u1_base.history[-1]["time_ns"] == 10000000000
    assert u2_base.history[-1]["time_ns"] == 15000000000
    assert u1_base.history[-1]["time_ns"] < u2_base.history[-1]["time_ns"]

    # 2. Run with ReverseOrderProvider:
    provider = ReverseOrderProvider()
    summary = run_episode(BASE_DECISION_YAML, decision_provider=provider)
    assert summary.status == "completed"
    assert len(provider.batches_seen) == 1
    batch = provider.batches_seen[0]
    assert batch.time_ns == 2000000000  # Pause at exactly 2s
    assert len(batch.requests) == 1

    req = batch.requests[0]
    assert req.target_id == "buf-1"
    obs = req.observation
    assert obs.buffer_id == "buf-1"
    assert obs.capacity == 5
    assert obs.occupancy == 2
    assert [occ.unit_id for occ in obs.occupants] == ["u-1", "u-2"]
    # Neighborhood has upstream stations and downstream station
    assert set(obs.upstream_nodes) == {"st-1a", "st-1b"}
    assert obs.downstream_nodes == ["st-2"]
    # Verify no latent quality state or internal references leaked
    assert not hasattr(obs, "quality_state")
    assert not hasattr(obs, "defects")
    for occ in obs.occupants:
        assert not hasattr(occ, "defects")
        assert not hasattr(occ, "quality_state")
        assert occ.findings_count == 0

    # Summary recorded the decision batch as applied with correct provenance
    assert len(summary.decision_batches) == 1
    rec = summary.decision_batches[0]
    assert rec["status"] == "applied"
    assert rec["provenance"]["provider_id"] == "reverse-provider"
    assert rec["provenance"]["model_id"] == "rule-v1"
    assert rec["actions"][0]["new_order"] == ["u-2", "u-1"]
    assert len(summary.decision_diagnostics) == 0

    # Under reverse order, u-2 was prioritized and departs st-2 first!
    u1 = next(u for u in summary.production_units if u.id == "u-1")
    u2 = next(u for u in summary.production_units if u.id == "u-2")
    assert u2.history[-1]["time_ns"] == 10000000000
    assert u1.history[-1]["time_ns"] == 15000000000
    assert u2.history[-1]["time_ns"] < u1.history[-1]["time_ns"]


class InvalidActionProvider(DecisionProvider):
    def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
        # Invalid action referencing non-existent unit ID
        return DecisionBatchResponse(
            batch_id=batch.batch_id,
            provenance=DecisionProvenance(
                episode_id=batch.episode_id,
                batch_id=batch.batch_id,
                provider_id="invalid-provider",
                model_id="rule-v1",
                prompt_id="prompt-invalid",
            ),
            actions=[
                BufferReorderAction(
                    target_id="buf-1",
                    new_order=["u-unknown", "u-1"],
                )
            ],
        )


def test_decision_invalid_response_triggers_fallback_with_diagnostics() -> None:
    provider = InvalidActionProvider()
    summary = run_episode(BASE_DECISION_YAML, decision_provider=provider)

    assert summary.status == "completed"
    assert len(summary.decision_batches) == 1
    batch_rec = summary.decision_batches[0]
    assert batch_rec["status"] == "fallback"

    # Explicit diagnostic record emitted
    assert len(summary.decision_diagnostics) >= 1
    codes = [d["code"] for d in summary.decision_diagnostics]
    assert "UNKNOWN_UNIT" in codes
    assert any("u-unknown" in d["message"] for d in summary.decision_diagnostics)

    # Fallback policy (FIFO) was applied, so u-1 completed before u-2
    u1 = next(u for u in summary.production_units if u.id == "u-1")
    u2 = next(u for u in summary.production_units if u.id == "u-2")
    assert u1.history[-1]["time_ns"] < u2.history[-1]["time_ns"]


class ConflictingActionProvider(DecisionProvider):
    def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
        # Conflicting actions: two distinct actions targeting the same buffer
        return DecisionBatchResponse(
            batch_id=batch.batch_id,
            provenance=DecisionProvenance(
                episode_id=batch.episode_id,
                batch_id=batch.batch_id,
                provider_id="conflict-provider",
                model_id="rule-v1",
                prompt_id="prompt-conflict",
            ),
            actions=[
                BufferReorderAction(target_id="buf-1", new_order=["u-1", "u-2"]),
                BufferReorderAction(target_id="buf-1", new_order=["u-2", "u-1"]),
            ],
        )


def test_decision_conflicting_response_triggers_fallback_with_diagnostics() -> None:
    provider = ConflictingActionProvider()
    summary = run_episode(BASE_DECISION_YAML, decision_provider=provider)

    assert summary.status == "completed"
    assert len(summary.decision_batches) == 1
    assert summary.decision_batches[0]["status"] == "fallback"

    assert len(summary.decision_diagnostics) >= 1
    diag = summary.decision_diagnostics[0]
    assert diag["code"] == "CONFLICTING_ACTIONS"
    assert "buf-1" in diag["message"]

    # Fallback FIFO applied
    u1 = next(u for u in summary.production_units if u.id == "u-1")
    u2 = next(u for u in summary.production_units if u.id == "u-2")
    assert u1.history[-1]["time_ns"] < u2.history[-1]["time_ns"]


def test_decision_abort_on_failure() -> None:
    abort_yaml = BASE_DECISION_YAML.replace('on_failure: "fallback"', 'on_failure: "abort"')
    provider = InvalidActionProvider()

    summary = run_episode(abort_yaml, decision_provider=provider)
    assert summary.status == "aborted"
    assert summary.is_aborted is True
    assert summary.abort_reason is not None
    assert "u-unknown" in summary.abort_reason

    # Diagnostic is recorded
    assert len(summary.decision_diagnostics) >= 1
    codes = [d["code"] for d in summary.decision_diagnostics]
    assert "UNKNOWN_UNIT" in codes


def test_decision_checkpoint_restore_determinism() -> None:
    # 1. Direct run with ReverseOrderProvider
    prov1 = ReverseOrderProvider()
    summary_direct = run_episode(BASE_DECISION_YAML, decision_provider=prov1)

    # 2. Run with checkpoint pausing at 3s (after decision at 2s)
    prov2 = ReverseOrderProvider()
    cp = create_checkpoint(BASE_DECISION_YAML, at_time_ns=3000000000, decision_provider=prov2)
    assert cp.simulated_time_ns == 3000000000
    assert len(prov2.batches_seen) == 1

    # Continue from checkpoint to completion
    summary_resumed = continue_checkpoint(cp, decision_provider=prov2)
    assert summary_resumed.status == "completed"

    # Compare direct vs checkpoint resumed:
    assert summary_direct.result_hash == summary_resumed.result_hash
    assert summary_direct.decision_batches == summary_resumed.decision_batches

    for u_d, u_r in zip(summary_direct.production_units, summary_resumed.production_units, strict=True):
        assert u_d.id == u_r.id
        assert u_d.history == u_r.history


def test_decision_time_invariance_and_rearm() -> None:
    # Verify that discrete simulation time does NOT advance while waiting for the decision provider,
    # and verify that triggers re-arm only after occupancy drops below threshold.
    class TimeCheckingProvider(DecisionProvider):
        def __init__(self) -> None:
            self.decision_times: list[int] = []

        def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
            self.decision_times.append(batch.time_ns)
            # Verify batch requests all share the exact same timestamp
            for req in batch.requests:
                assert req.time_ns == batch.time_ns
            actions = [
                BufferReorderAction(
                    target_id=req.target_id,
                    new_order=[occ.unit_id for occ in req.observation.occupants],
                )
                for req in batch.requests
            ]
            return DecisionBatchResponse(
                batch_id=batch.batch_id,
                provenance=DecisionProvenance(
                    episode_id=batch.episode_id,
                    batch_id=batch.batch_id,
                    provider_id="time-checker",
                ),
                actions=actions,
            )

    provider = TimeCheckingProvider()
    summary = run_episode(BASE_DECISION_YAML, decision_provider=provider)
    assert summary.status == "completed"
    assert len(provider.decision_times) == 1
    # Exactly at 2 seconds (2_000_000_000 ns)
    assert provider.decision_times[0] == 2_000_000_000


def test_decision_unrequested_target_triggers_fallback_and_diagnostic() -> None:
    class UnrequestedTargetProvider(DecisionProvider):
        def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
            return DecisionBatchResponse(
                batch_id=batch.batch_id,
                provenance=DecisionProvenance(
                    episode_id=batch.episode_id,
                    batch_id=batch.batch_id,
                    provider_id="unrequested-provider",
                ),
                actions=[
                    BufferReorderAction(target_id="buf-1", new_order=["u-2", "u-1"]),
                    BufferReorderAction(target_id="buf-fake", new_order=["u-fake"]),
                ],
            )

    provider = UnrequestedTargetProvider()
    summary = run_episode(BASE_DECISION_YAML, decision_provider=provider)
    assert summary.status == "completed"
    assert len(summary.decision_batches) == 1
    assert summary.decision_batches[0]["status"] == "fallback"

    codes = [d["code"] for d in summary.decision_diagnostics]
    assert "UNREQUESTED_TARGET" in codes
    # FIFO fallback applied (u-1 finishes before u-2)
    u1 = next(u for u in summary.production_units if u.id == "u-1")
    u2 = next(u for u in summary.production_units if u.id == "u-2")
    assert u1.history[-1]["time_ns"] < u2.history[-1]["time_ns"]

import pytest
from industrialsim.application import run_episode, EpisodeSummary
from industrialsim.decisions import (
    BaselineDecisionProvider,
    DecisionProvider,
    DecisionBatch,
    DecisionBatchResponse,
    DecisionProvenance,
    BufferReorderAction,
    ReconfigurationAction,
    QualityControlAction,
    DecisionAction,
)

BASE_ACTIONS_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

material_flow:
  nodes:
    - id: "src-blocker"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "conveyor"
          direction: "output"
    - id: "src-units"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "conveyor"
          direction: "output"
    - id: "buf-1"
      kind: "buffer"
      capacity: 10
      input_ports:
        - id: "p-in"
          port_type: "conveyor"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "conveyor"
          direction: "output"
    - id: "st-1"
      kind: "station"
      operations:
        - id: "op-process"
          duration: "5s"
      input_ports:
        - id: "p-in-blocker"
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
    - id: "r-blocker-st1"
      source_node_id: "src-blocker"
      source_port_id: "p-out"
      target_node_id: "st-1"
      target_port_id: "p-in-blocker"
      transit_time: "0s"
    - id: "r-src-buf"
      source_node_id: "src-units"
      source_port_id: "p-out"
      target_node_id: "buf-1"
      target_port_id: "p-in"
      transit_time: "0s"
    - id: "r-buf-st1"
      source_node_id: "buf-1"
      source_port_id: "p-out"
      target_node_id: "st-1"
      target_port_id: "p-in-buf"
      transit_time: "0s"
    - id: "r-st1-snk"
      source_node_id: "st-1"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"
      transit_time: "0s"

production_units:
  - id: "u-blocker"
    source_id: "src-blocker"
    variant: "blocker"
    release_time: "0s"
  - id: "u-std-1"
    source_id: "src-units"
    variant: "standard"
    release_time: "0s"
    due_date: "50s"
  - id: "u-std-2"
    source_id: "src-units"
    variant: "standard"
    release_time: "1s"
    due_date: "60s"
  - id: "u-urg-1"
    source_id: "src-units"
    variant: "urgent"
    release_time: "2s"
    due_date: "15s"

decision_triggers:
  - id: "trig-buf-rising"
    trigger_type: "buffer_threshold"
    buffer_id: "buf-1"
    threshold: 3
    direction: "rising"
    rearm_threshold: 1
    on_failure: "fallback"
    fallback_policy: "baseline"
"""


def test_baseline_provider_runs_e2e_and_satisfies_invariants() -> None:
    provider = BaselineDecisionProvider()
    summary: EpisodeSummary = run_episode(BASE_ACTIONS_YAML, decision_provider=provider)

    assert summary.status == "completed"
    assert len(summary.production_units) == 4
    # Check that decision batch was formed and applied
    assert len(summary.decision_batches) >= 1
    assert all(b["status"] == "applied" for b in summary.decision_batches)
    applied_batch = summary.decision_batches[0]
    action = applied_batch["actions"][0]
    assert action["action_type"] == "buffer_reorder"
    # FIFO with due date tie-breaker orders standard units before urgent unit (due to arrival times: 0s, 1s, 2s)
    assert action["new_order"] == ["u-std-1", "u-std-2", "u-urg-1"]


def test_custom_provider_vs_baseline_produces_different_valid_outcomes() -> None:
    """Verifies requirement 7: Baseline and custom providers produce different valid outcomes from same Episode input."""
    # 1. Run with Baseline Provider (FIFO priority)
    baseline_provider = BaselineDecisionProvider()
    summary_baseline = run_episode(BASE_ACTIONS_YAML, decision_provider=baseline_provider)
    assert summary_baseline.status == "completed"

    # 2. Run with Custom Due-Date Priority Provider (prioritizes earliest due dates over FIFO arrival)
    class EarliestDueDatePriorityProvider(DecisionProvider):
        def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
            actions = []
            for req in batch.requests:
                obs = req.observation
                sorted_occupants = sorted(
                    obs.occupants,
                    key=lambda occ: (
                        (0, occ.due_date_ns) if occ.due_date_ns is not None else (1, 0),
                        occ.enter_time_ns if occ.enter_time_ns is not None else 0,
                    ),
                )
                actions.append(
                    BufferReorderAction(
                        target_id=req.target_id,
                        new_order=[occ.unit_id for occ in sorted_occupants],
                    )
                )
            return DecisionBatchResponse(
                batch_id=batch.batch_id,
                provenance=DecisionProvenance(
                    episode_id=batch.episode_id,
                    batch_id=batch.batch_id,
                    provider_id="custom-edd-provider",
                ),
                actions=actions,
            )

    edd_provider = EarliestDueDatePriorityProvider()
    summary_custom = run_episode(BASE_ACTIONS_YAML, decision_provider=edd_provider)
    assert summary_custom.status == "completed"

    # In the custom run, urgent unit (u-urg-1) was prioritized ahead of standard units!
    u_urg_baseline = next(u for u in summary_baseline.production_units if u.id == "u-urg-1")
    u_urg_custom = next(u for u in summary_custom.production_units if u.id == "u-urg-1")

    t_finish_baseline = u_urg_baseline.history[-1]["time_ns"]
    t_finish_custom = u_urg_custom.history[-1]["time_ns"]

    # Urgent unit finishes 10s earlier in custom run (10s vs 20s)
    assert t_finish_custom < t_finish_baseline, (
        f"Custom EDD provider ({t_finish_custom}ns) did not prioritize urgent unit over baseline ({t_finish_baseline}ns)"
    )

    # Hashes and outcomes are demonstrably different
    assert summary_custom.result_hash != summary_baseline.result_hash


def test_strategic_action_duration_and_cost_tracking() -> None:
    """Verifies requirement 2: Strategic Actions accepted at safe points carry duration and cost."""
    yaml_with_safe_point = BASE_ACTIONS_YAML + """
  - id: "trig-safe-0s"
    trigger_type: "safe_point"
    target_id: "st-1"
    times_ns: [0]
    on_failure: "fallback"
    fallback_policy: "baseline"
"""

    class StrategicReconfigProvider(DecisionProvider):
        def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
            actions: list[DecisionAction] = []
            for req in batch.requests:
                if req.request_type == "strategic" and req.is_safe_point:
                    actions.append(
                        ReconfigurationAction(
                            target_id="st-1",
                            configuration={"tooling": "high_precision"},
                            duration_ns=4_000_000_000,  # 4s setup duration
                            cost=250.0,
                        )
                    )
                elif req.request_type == "buffer_threshold":
                    actions.append(
                        BufferReorderAction(
                            target_id=req.target_id,
                            new_order=[occ.unit_id for occ in req.observation.occupants],
                        )
                    )
            return DecisionBatchResponse(
                batch_id=batch.batch_id,
                provenance=DecisionProvenance(
                    episode_id=batch.episode_id,
                    batch_id=batch.batch_id,
                    provider_id="strat-provider",
                ),
                actions=actions,
            )

    summary = run_episode(yaml_with_safe_point, decision_provider=StrategicReconfigProvider())
    assert summary.status == "completed"

    # Verify strategic cost was recorded
    assert hasattr(summary, "total_strategic_cost")
    assert summary.total_strategic_cost == 250.0

    # Verify strategic batch was applied
    strat_batch = next(
        b for b in summary.decision_batches if any(a.get("action_type") == "reconfiguration" for a in b.get("actions", []))
    )
    assert strat_batch["status"] == "applied"


def test_competing_resource_claims_in_live_simulation_rejected_as_batch() -> None:
    """Verifies requirement 5: Simultaneous actions with competing claims are rejected as a batch."""
    class ConflictingClaimsProvider(DecisionProvider):
        def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
            return DecisionBatchResponse(
                batch_id=batch.batch_id,
                provenance=DecisionProvenance(
                    episode_id=batch.episode_id,
                    batch_id=batch.batch_id,
                    provider_id="conflict-provider",
                ),
                actions=[
                    BufferReorderAction(target_id="buf-1", new_order=["u-std-1", "u-std-2", "u-urg-1"]),
                    BufferReorderAction(target_id="buf-1", new_order=["u-urg-1", "u-std-1", "u-std-2"]),
                ],
            )

    summary = run_episode(BASE_ACTIONS_YAML, decision_provider=ConflictingClaimsProvider())
    assert len(summary.decision_batches) >= 1
    conflict_batch = summary.decision_batches[0]
    assert conflict_batch["status"] == "fallback"
    assert any(d["code"] == "CONFLICTING_ACTIONS" for d in summary.decision_diagnostics)


def test_unsafe_decision_point_strategic_action_rejected_and_falls_back() -> None:
    """Verifies requirement 2: Strategic Actions rejected when not at safe decision point."""
    class UnsafeStrategicProvider(DecisionProvider):
        def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
            # Tries to perform reconfiguration on a buffer trigger (is_safe_point is False)
            return DecisionBatchResponse(
                batch_id=batch.batch_id,
                provenance=DecisionProvenance(
                    episode_id=batch.episode_id,
                    batch_id=batch.batch_id,
                    provider_id="unsafe-strat-provider",
                ),
                actions=[
                    ReconfigurationAction(
                        target_id="buf-1",
                        configuration={"layout": "dense"},
                        duration_ns=1_000_000_000,
                        cost=50.0,
                    )
                ],
            )

    summary = run_episode(BASE_ACTIONS_YAML, decision_provider=UnsafeStrategicProvider())
    assert len(summary.decision_batches) >= 1
    unsafe_batch = summary.decision_batches[0]
    assert unsafe_batch["status"] == "fallback"
    assert any(d["code"] == "UNSAFE_DECISION_POINT" for d in summary.decision_diagnostics)


def test_quality_control_bounds_enforced_and_exceeded_rejected() -> None:
    """Verifies requirement 3: Quality Actions rejected when exceeding configured bounds."""
    yaml_with_bounds = BASE_ACTIONS_YAML + """
  - id: "trig-safe-qc"
    trigger_type: "safe_point"
    target_id: "st-1"
    times_ns: [3000000000]
    quality_bounds:
      min_inspection_intensity: 0.2
      max_inspection_intensity: 0.8
    on_failure: "fallback"
    fallback_policy: "baseline"
"""

    class OutOfBoundsQCProvider(DecisionProvider):
        def decide(self, batch: DecisionBatch) -> DecisionBatchResponse:
            actions: list[DecisionAction] = []
            for req in batch.requests:
                if req.request_type == "strategic":
                    actions.append(
                        QualityControlAction(
                            target_id="st-1",
                            inspection_intensity=0.95,  # Exceeds max 0.8!
                            cost=10.0,
                        )
                    )
                elif req.request_type == "buffer_threshold":
                    actions.append(
                        BufferReorderAction(
                            target_id=req.target_id,
                            new_order=[occ.unit_id for occ in req.observation.occupants],
                        )
                    )
            return DecisionBatchResponse(
                batch_id=batch.batch_id,
                provenance=DecisionProvenance(
                    episode_id=batch.episode_id,
                    batch_id=batch.batch_id,
                    provider_id="oob-qc-provider",
                ),
                actions=actions,
            )

    summary = run_episode(yaml_with_bounds, decision_provider=OutOfBoundsQCProvider())
    assert any(d["code"] == "QUALITY_BOUNDS_EXCEEDED" for d in summary.decision_diagnostics)

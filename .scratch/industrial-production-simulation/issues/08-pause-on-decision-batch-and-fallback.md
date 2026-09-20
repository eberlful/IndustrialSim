# 08: Pause on a Decision Batch and recover by Fallback Policy

**What to build:** Pause an entire Episode at a consistent Buffer-related decision point, expose a bounded versioned observation and action schema to an in-process Decision Provider, and continue atomically with either valid Actions or a deterministic Fallback Policy.

**Blocked by:** 02: Move Production Units through typed material flow.

Status: resolved

- [x] A Buffer threshold state transition emits a typed, versioned Decision Request with local detail, relevant neighborhood, aggregate metrics, and bounded history.
- [x] Requests at the same pause point form one Decision Batch and observe the same immutable simulation state.
- [x] No simulation time advances while waiting for the Decision Provider.
- [x] Responses are jointly validated before any Action is applied, and valid Actions take effect atomically.
- [x] Invalid, missing, or conflicting responses produce explicit diagnostics and invoke the configured Fallback Policy or configured Episode abort.
- [x] A Trigger uses re-arm or hysteresis plus a deduplication key and cannot loop indefinitely on unchanged state.
- [x] The contract carries Episode, Branch, Batch, Provider, model, and prompt provenance without exposing internal objects.
- [x] End-to-end tests compare valid provider response, invalid response, conflict, Fallback, and abort outcomes.

## Answer

Issue 08 has been fully implemented across configuration, decision contracts, triggers, batch coordination, discrete-event simulation engine, checkpoints, and test suites:

1. **Typed, Versioned Decision Contracts (ADR 0006)**:
   - Defined Pydantic models in `src/industrialsim/decisions.py`: `BufferObservation`, `BufferOccupantSummary`, `BufferReorderAction`, `DecisionRequest`, `DecisionBatch`, `DecisionBatchResponse`, `DecisionDiagnosticRecord`, and `DecisionProvenance`.
   - Strictly quarantined latent quality (`quality_state`, `defects`) from observations; only observable counts (`findings_count`, `rework_count`) are included.
   - Observations package buffer capacity, current occupancy, occupants list, relevant neighborhood (upstream/downstream node IDs and route statuses), aggregate plant metrics, and bounded buffer history.

2. **Consistent Pause Points & Decision Batch Coordination (ADR 0003)**:
   - `DecisionBatchCoordinator` aggregates all decision requests emitted at the same pause point into a single `DecisionBatch`.
   - Discrete simulation time does not advance while waiting for the provider (`k.current_time_ns` remains constant; events in the priority queue do not step during decision batch resolution).
   - In `_can_unit_depart`, departures from buffers with pending decision requests are held until the decision batch has completed.

3. **Joint Action Validation & Atomic Application**:
   - `validate_decision_batch_response` jointly validates all proposed actions in a batch before applying any: checks matching batch ID, valid target buffer IDs, exact occupant set equality (all current occupants must be present without duplicates or unknown units), and detects conflicting duplicate actions for the same buffer.
   - Valid actions apply atomically across all targeted buffers in `_apply_decision_actions`.

4. **Fallback Policies & Episode Abort Handling**:
   - When a decision provider is missing, returns an invalid response, produces conflicting actions, or raises an exception:
     - Structured `DecisionDiagnosticRecord` entries are generated and appended to `summary.decision_diagnostics`.
     - If the trigger is configured with `on_failure: "fallback"`, the deterministic `FifoBufferFallbackPolicy` is invoked (preserving FIFO order) and the batch is recorded with status `"fallback"`.
     - If the trigger is configured with `on_failure: "abort"`, the episode terminates immediately (`status="aborted"`, `is_aborted=True`, and `abort_reason` set with diagnostics).

5. **Hysteresis, Re-arming & Deduplication (ADR 0003)**:
   - `BufferThresholdTriggerConfig` and `BufferTriggerRuntime` evaluate transitions along configured directions (`rising`, `falling`, `both`).
   - Hysteresis re-arming prevents infinite loops: for `rising`, re-arming occurs only when occupancy drops below the threshold; for `falling`, re-arming occurs only when occupancy rises above the threshold.
   - Deduplication key tracking and per-timestamp limits (`max_triggers_per_timestamp`) ensure unchanged states do not trigger multiple decision pauses.

6. **Checkpoints & Bit-for-Bit Determinism (ADR 0009)**:
   - Added `decision_triggers`, `decision_coordinator`, `decision_diagnostics`, and `decision_batches` to `DomainStateSnapshot` and `compute_model_hash`.
   - `EpisodeEngine.restore`, `create_checkpoint`, and `continue_checkpoint` restore decision coordinator state and runtime trigger state, ensuring exact bit-for-bit replay and hash equivalence between direct and resumed runs.

7. **Verification & Testing**:
   - Unit tests in `tests/test_decision_contracts.py`: schema serialization, joint validation, conflict detection, fallback policy.
   - Unit tests in `tests/test_decision_triggers.py`: trigger activation, re-arm hysteresis, dedup loop prevention, batch coordinator.
   - E2E tests in `tests/test_decision_simulation_e2e.py`: atomic buffer reordering with valid provider, invalid response triggering fallback with diagnostics, conflicting response triggering fallback, episode abort on failure, time invariance during decision pause, and checkpoint resume determinism.

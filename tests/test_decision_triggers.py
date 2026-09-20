import pytest
from industrialsim.config import BufferThresholdTriggerConfig
from industrialsim.decisions import BufferTriggerRuntime


def test_buffer_trigger_rising_threshold_and_rearm_hysteresis() -> None:
    cfg = BufferThresholdTriggerConfig(
        id="trig-1",
        buffer_id="buf-1",
        threshold=2,
        direction="rising",
        rearm_threshold=1,
    )
    runtime = BufferTriggerRuntime(config=cfg)

    # 1. Occupancy increases from 0 -> 1: threshold (2) not reached
    assert runtime.check_transition(buffer_id="buf-1", old_occupancy=0, new_occupancy=1, current_time_ns=1000) is False

    # 2. Occupancy increases from 1 -> 2: threshold reached -> FIRES
    assert runtime.check_transition(buffer_id="buf-1", old_occupancy=1, new_occupancy=2, current_time_ns=2000) is True

    # 3. Trigger is now disarmed. Occupancy remains at 2 or increases to 3 -> does NOT fire
    assert runtime.check_transition(buffer_id="buf-1", old_occupancy=2, new_occupancy=3, current_time_ns=3000) is False

    # 4. Occupancy drops from 3 to 2 -> still above rearm_threshold (1), stays disarmed
    assert runtime.check_transition(buffer_id="buf-1", old_occupancy=3, new_occupancy=2, current_time_ns=4000) is False

    # 5. Occupancy drops to 1 -> re-arms!
    assert runtime.check_transition(buffer_id="buf-1", old_occupancy=2, new_occupancy=1, current_time_ns=5000) is False
    assert runtime.is_armed is True

    # 6. Occupancy increases again to 2 -> FIRES again
    assert runtime.check_transition(buffer_id="buf-1", old_occupancy=1, new_occupancy=2, current_time_ns=6000) is True


def test_buffer_trigger_deduplication_key_prevents_looping() -> None:
    cfg = BufferThresholdTriggerConfig(
        id="trig-1",
        buffer_id="buf-1",
        threshold=1,
        direction="rising",
        rearm_threshold=0,
    )
    runtime = BufferTriggerRuntime(config=cfg)

    # Fire at t=1000
    assert runtime.check_transition(buffer_id="buf-1", old_occupancy=0, new_occupancy=1, current_time_ns=1000) is True

    # Unchanged state or identical transition at same timestamp cannot loop indefinitely
    assert runtime.check_transition(buffer_id="buf-1", old_occupancy=0, new_occupancy=1, current_time_ns=1000) is False
    assert runtime.check_transition(buffer_id="buf-1", old_occupancy=1, new_occupancy=1, current_time_ns=1000) is False


def test_batch_coordination_groups_multiple_requests_at_same_timestamp() -> None:
    from industrialsim.decisions import DecisionBatchCoordinator, DecisionRequest, BufferObservation

    coord = DecisionBatchCoordinator(episode_id="ep-01")

    req1 = DecisionRequest(
        request_id="req-1",
        request_type="buffer_threshold",
        time_ns=5000,
        target_id="buf-1",
        observation=BufferObservation(buffer_id="buf-1", capacity=5, occupancy=2),
    )
    req2 = DecisionRequest(
        request_id="req-2",
        request_type="buffer_threshold",
        time_ns=5000,
        target_id="buf-2",
        observation=BufferObservation(buffer_id="buf-2", capacity=5, occupancy=3),
    )

    coord.add_request(req1)
    coord.add_request(req2)

    batch = coord.form_batch(time_ns=5000)
    assert batch is not None
    assert batch.time_ns == 5000
    assert batch.episode_id == "ep-01"
    assert len(batch.requests) == 2
    assert [r.target_id for r in batch.requests] == ["buf-1", "buf-2"]

    # Once formed, coordinator clears pending requests for that batch
    assert coord.has_pending() is False


def test_machine_trigger_runtime_hysteresis_and_dedup() -> None:
    from industrialsim.config import MachineDecisionTriggerConfig
    from industrialsim.decisions import MachineTriggerRuntime

    cfg = MachineDecisionTriggerConfig(
        id="trig-m1",
        machine_id="mach-1",
        health_threshold=0.3,
        rearm_threshold=0.7,
    )
    runtime = MachineTriggerRuntime(config=cfg)

    # 1. Health drops from 0.8 to 0.4 -> above threshold (0.3), does not fire
    assert runtime.check_condition(machine_id="mach-1", health=0.4, current_time_ns=1000) is False

    # 2. Health drops to 0.25 -> <= 0.3 -> FIRES
    assert runtime.check_condition(machine_id="mach-1", health=0.25, current_time_ns=2000) is True

    # 3. Disarmed: does not fire repeatedly on same/lower health
    assert runtime.check_condition(machine_id="mach-1", health=0.20, current_time_ns=3000) is False

    # 4. Dedup key prevents firing at same timestamp even if re-evaluated
    assert runtime.check_condition(machine_id="mach-1", health=0.20, current_time_ns=2000) is False

    # 5. Maintenance completed, health restored to 0.9 -> re-arms!
    assert runtime.check_condition(machine_id="mach-1", health=0.9, current_time_ns=4000) is False
    assert runtime.is_armed is True

    # 6. Health drops again to 0.28 -> FIRES again
    assert runtime.check_condition(machine_id="mach-1", health=0.28, current_time_ns=5000) is True


def test_safe_point_trigger_runtime() -> None:
    from industrialsim.config import SafePointTriggerConfig
    from industrialsim.decisions import SafePointTriggerRuntime

    cfg = SafePointTriggerConfig(
        id="trig-safe-1",
        target_id="st-1",
        times_ns=[10_000_000, 20_000_000],
    )
    runtime = SafePointTriggerRuntime(config=cfg)

    # At t=5_000_000, not a scheduled time
    assert runtime.check_time(current_time_ns=5_000_000) is False

    # At t=10_000_000, matches scheduled safe point -> FIRES
    assert runtime.check_time(current_time_ns=10_000_000) is True

    # Dedup check: same time cannot fire again
    assert runtime.check_time(current_time_ns=10_000_000) is False

    # Next scheduled safe point at t=20_000_000 -> FIRES
    assert runtime.check_time(current_time_ns=20_000_000) is True


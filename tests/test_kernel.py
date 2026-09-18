import pytest
from industrialsim.kernel import EventKernel, ScheduledEvent, EventPriority


def test_kernel_orders_events_by_time_priority_and_monotonic_sequence() -> None:
    kernel = EventKernel()
    processed: list[str] = []

    def handler(kernel: EventKernel, event: ScheduledEvent) -> None:
        processed.append(event.payload["name"])

    kernel.register_handler("test_event", handler)

    # Schedule out of order
    # Same time (1000ns), different priority
    kernel.schedule(
        time_ns=1000,
        priority=EventPriority.NEW_WORK,
        event_type="test_event",
        payload={"name": "work_at_1000"},
    )
    kernel.schedule(
        time_ns=1000,
        priority=EventPriority.COMPLETION,
        event_type="test_event",
        payload={"name": "completion_at_1000"},
    )
    # Earlier time (500ns)
    kernel.schedule(
        time_ns=500,
        priority=EventPriority.NEW_WORK,
        event_type="test_event",
        payload={"name": "work_at_500"},
    )
    # Same time (1000ns), same priority (COMPLETION), scheduled after first completion
    kernel.schedule(
        time_ns=1000,
        priority=EventPriority.COMPLETION,
        event_type="test_event",
        payload={"name": "second_completion_at_1000"},
    )

    kernel.run_until_empty()

    assert processed == [
        "work_at_500",
        "completion_at_1000",
        "second_completion_at_1000",
        "work_at_1000",
    ]
    assert kernel.current_time_ns == 1000


def test_kernel_rejects_non_integer_time() -> None:
    kernel = EventKernel()
    with pytest.raises(TypeError, match="integer nanoseconds"):
        kernel.schedule(
            time_ns=10.5,  # type: ignore[arg-type]
            priority=EventPriority.NEW_WORK,
            event_type="test_event",
            payload={},
        )


from hypothesis import given, strategies as st


@given(
    st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=10_000_000),
            st.integers(min_value=0, max_value=100),
        ),
        min_size=1,
        max_size=100,
    )
)
def test_property_monotonic_time_and_stable_tie_breaking(
    events_spec: list[tuple[int, int]],
) -> None:
    kernel = EventKernel()
    processed_tuples: list[tuple[int, int, int]] = []

    def handler(k: EventKernel, event: ScheduledEvent) -> None:
        processed_tuples.append((event.time_ns, event.priority, event.sequence))

    kernel.register_handler("evt", handler)

    for time_ns, prio in events_spec:
        kernel.schedule(
            time_ns=time_ns,
            priority=prio,
            event_type="evt",
            payload={},
        )

    kernel.run_until_empty()

    # 1. Verify monotonic time: t_{i+1} >= t_i
    for i in range(len(processed_tuples) - 1):
        assert processed_tuples[i][0] <= processed_tuples[i + 1][0]

    # 2. Verify strict total ordering by (time_ns, priority, sequence)
    for i in range(len(processed_tuples) - 1):
        t1, p1, s1 = processed_tuples[i]
        t2, p2, s2 = processed_tuples[i + 1]
        assert (t1, p1, s1) < (t2, p2, s2)


def test_kernel_snapshot_and_restore() -> None:
    kernel = EventKernel(initial_time_ns=100)
    kernel.schedule(time_ns=200, priority=EventPriority.NEW_WORK, event_type="work", payload={"id": 1})
    kernel.schedule(time_ns=300, priority=EventPriority.COMPLETION, event_type="comp", payload={"id": 2})

    snap = kernel.snapshot()
    assert snap["current_time_ns"] == 100
    assert len(snap["queue"]) == 2

    new_kernel = EventKernel()
    new_kernel.restore(snap)

    assert new_kernel.current_time_ns == 100
    assert new_kernel.queue_size == 2

    evt1 = new_kernel.step()
    assert evt1 is not None
    assert evt1.time_ns == 200
    assert evt1.payload["id"] == 1

    evt2 = new_kernel.step()
    assert evt2 is not None
    assert evt2.time_ns == 300
    assert evt2.payload["id"] == 2



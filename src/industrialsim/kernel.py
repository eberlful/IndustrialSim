from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
import heapq
from typing import Any, Callable


class EventPriority(IntEnum):
    SAFETY = 10
    FAILURE = 20
    COMPLETION = 30
    RESOURCE = 40
    NEW_WORK = 50
    TELEMETRY = 60


@dataclass(frozen=True)
class ScheduledEvent:
    time_ns: int
    priority: int
    sequence: int
    event_type: str
    payload_version: int = 1
    payload: dict[str, Any] = field(default_factory=dict)


EventHandler = Callable[["EventKernel", ScheduledEvent], None]


class EventKernel:
    def __init__(self, initial_time_ns: int = 0) -> None:
        if not isinstance(initial_time_ns, int) or isinstance(initial_time_ns, bool):
            raise TypeError(f"initial_time_ns must be integer nanoseconds, got {type(initial_time_ns).__name__}")
        if initial_time_ns < 0:
            raise ValueError(f"initial_time_ns cannot be negative: {initial_time_ns}")

        self._current_time_ns: int = initial_time_ns
        self._sequence_counter: int = 0
        self._queue: list[tuple[int, int, int, ScheduledEvent]] = []
        self._handlers: dict[str, EventHandler] = {}
        self._events_processed: int = 0

    @property
    def current_time_ns(self) -> int:
        return self._current_time_ns

    @property
    def events_processed(self) -> int:
        return self._events_processed

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    def register_handler(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type] = handler

    def advance_to(self, time_ns: int) -> None:
        if not isinstance(time_ns, int) or isinstance(time_ns, bool):
            raise TypeError(f"time_ns must be integer nanoseconds, got {type(time_ns).__name__}")
        if time_ns < self._current_time_ns:
            raise ValueError(f"Cannot rewind time: {time_ns} < {self._current_time_ns}")
        if self._queue and self._queue[0][0] < time_ns:
            raise ValueError(
                f"Cannot advance time past pending events: next event at {self._queue[0][0]} < {time_ns}"
            )
        self._current_time_ns = time_ns

    def schedule(
        self,
        time_ns: int,
        priority: int | EventPriority,
        event_type: str,
        payload: dict[str, Any] | None = None,
        payload_version: int = 1,
    ) -> ScheduledEvent:
        if not isinstance(time_ns, int) or isinstance(time_ns, bool):
            raise TypeError(f"time_ns must be integer nanoseconds, got {type(time_ns).__name__}")
        if time_ns < self._current_time_ns:
            raise ValueError(
                f"Cannot schedule event in past: {time_ns} < current {self._current_time_ns}"
            )

        priority_val = int(priority)
        self._sequence_counter += 1
        seq = self._sequence_counter
        event = ScheduledEvent(
            time_ns=time_ns,
            priority=priority_val,
            sequence=seq,
            event_type=event_type,
            payload_version=payload_version,
            payload=payload if payload is not None else {},
        )
        heapq.heappush(self._queue, (time_ns, priority_val, seq, event))
        return event

    def step(self) -> ScheduledEvent | None:
        if not self._queue:
            return None

        time_ns, priority_val, seq, event = heapq.heappop(self._queue)
        self._current_time_ns = time_ns
        self._events_processed += 1

        handler = self._handlers.get(event.event_type)
        if handler is not None:
            handler(self, event)

        return event

    def run_until_empty(self) -> int:
        count = 0
        while self._queue:
            self.step()
            count += 1
        return count

    def run_until(
        self,
        max_time_ns: int | None = None,
        stop_condition: Callable[["EventKernel"], bool] | None = None,
    ) -> int:
        count = 0
        while self._queue:
            if stop_condition is not None and stop_condition(self):
                break
            # peek next event time
            next_time = self._queue[0][0]
            if max_time_ns is not None and next_time > max_time_ns:
                break
            self.step()
            count += 1
            if stop_condition is not None and stop_condition(self):
                break
        return count

    def snapshot(self) -> dict[str, Any]:
        return {
            "current_time_ns": self._current_time_ns,
            "sequence_counter": self._sequence_counter,
            "events_processed": self._events_processed,
            "queue": [
                {
                    "time_ns": item[3].time_ns,
                    "priority": item[3].priority,
                    "sequence": item[3].sequence,
                    "event_type": item[3].event_type,
                    "payload_version": item[3].payload_version,
                    "payload": item[3].payload,
                }
                for item in self._queue
            ],
        }

    def restore(self, state: dict[str, Any]) -> None:
        self._current_time_ns = state["current_time_ns"]
        self._sequence_counter = state["sequence_counter"]
        self._events_processed = state["events_processed"]
        self._queue = []
        for item in state["queue"]:
            event = ScheduledEvent(
                time_ns=item["time_ns"],
                priority=item["priority"],
                sequence=item["sequence"],
                event_type=item["event_type"],
                payload_version=item.get("payload_version", 1),
                payload=item.get("payload", {}),
            )
            heapq.heappush(
                self._queue,
                (event.time_ns, event.priority, event.sequence, event),
            )


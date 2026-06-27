"""Virtualized time source for deterministic replay.

Decision D5: virtualize within run scope via context manager, NOT global
import-time patching (which pollutes the host process).

In **record mode**, ``now()`` calls ``datetime.now()`` for real, records
the value as a ``ClockEvent``, and returns it.

In **replay mode**, ``now()`` returns the next recorded value in sequence.

Agent code must call ``agentreplay.now()`` instead of ``datetime.now()``
for interception to work. Direct ``datetime.now()`` calls are a documented
v1 limitation — they bypass interception and produce non-deterministic
replays for that specific value.
"""

from __future__ import annotations

import contextvars
from datetime import datetime, timezone

from agentreplay.recorder.collector import TraceCollector
from agentreplay.schema.trace import ClockEvent, EventType

# Context variable so nested/concurrent runs don't interfere.
_active_clock: contextvars.ContextVar[VirtualClock | None] = contextvars.ContextVar(
    "_active_clock", default=None,
)


class VirtualClock:
    """Context manager that virtualizes time within a recording session.

    Usage::

        clock = VirtualClock(collector, mode="record")
        with clock:
            t = agentreplay.now()  # records and returns real time
    """

    def __init__(self, collector: TraceCollector, mode: str = "record") -> None:
        self._collector = collector
        self._mode = mode
        self._cursor = 0
        self._token: contextvars.Token | None = None

    def __enter__(self) -> VirtualClock:
        self._token = _active_clock.set(self)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._token is not None:
            _active_clock.reset(self._token)

    def now(self, tz: timezone | None = None) -> datetime:
        """Record-or-replay a ``datetime.now()`` call."""
        if self._mode == "record":
            real_time = datetime.now(tz or timezone.utc)
            event = ClockEvent(
                seq=self._collector.next_seq(),
                recorded_time=real_time,
            )
            self._collector.add_event(event)
            return real_time

        # Replay: serve from recorded events in order.
        clock_events = self._collector.trace.get_events_by_type(EventType.CLOCK)
        if self._cursor >= len(clock_events):
            raise LookupError(
                f"REPLAY MISS: no more recorded clock events "
                f"(expected index {self._cursor})"
            )
        event = clock_events[self._cursor]
        self._cursor += 1
        return event.recorded_time


def now(tz: timezone | None = None) -> datetime:
    """Drop-in replacement for ``datetime.now()``.

    If a ``VirtualClock`` is active (inside a ``wrap()`` context), records
    or replays. Otherwise falls through to real ``datetime.now()``.
    """
    clock = _active_clock.get()
    if clock is not None:
        return clock.now(tz)
    return datetime.now(tz or timezone.utc)

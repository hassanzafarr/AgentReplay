"""Tests for agentreplay.recorder.clock — virtualized time.

Proves: record mode captures real time, replay mode returns recorded
values in order, VirtualClock context manager scopes correctly.

Does NOT cover: concurrent access, timezone edge cases.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agentreplay.recorder.clock import VirtualClock, now
from agentreplay.recorder.collector import TraceCollector
from agentreplay.schema.trace import EventType


class TestVirtualClockRecord:
    def test_records_real_time(self):
        """Record mode captures a real datetime value."""
        collector = TraceCollector()
        clock = VirtualClock(collector, mode="record")

        with clock:
            before = datetime.now(timezone.utc)
            t = now()
            after = datetime.now(timezone.utc)

        assert before <= t <= after

    def test_records_clock_event(self):
        """Record mode adds a ClockEvent to the collector."""
        collector = TraceCollector()
        clock = VirtualClock(collector, mode="record")

        with clock:
            now()

        events = collector.trace.get_events_by_type(EventType.CLOCK)
        assert len(events) == 1
        assert events[0].seq == 0

    def test_multiple_calls(self):
        """Multiple now() calls get separate events."""
        collector = TraceCollector()
        clock = VirtualClock(collector, mode="record")

        with clock:
            now()
            now()
            now()

        events = collector.trace.get_events_by_type(EventType.CLOCK)
        assert len(events) == 3


class TestVirtualClockReplay:
    def test_returns_recorded_values(self):
        """Replay mode returns the exact recorded times in order."""
        collector = TraceCollector()
        clock = VirtualClock(collector, mode="record")

        with clock:
            t1 = now()
            t2 = now()

        # Replay.
        replay_clock = VirtualClock(collector, mode="replay")
        with replay_clock:
            r1 = now()
            r2 = now()

        assert r1 == t1
        assert r2 == t2

    def test_replay_miss_raises(self):
        """Exhausting recorded clock events raises LookupError."""
        collector = TraceCollector()
        clock = VirtualClock(collector, mode="record")

        with clock:
            now()  # Record one event.

        replay_clock = VirtualClock(collector, mode="replay")
        with replay_clock:
            now()  # Consume the one event.
            with pytest.raises(LookupError, match="REPLAY MISS"):
                now()  # No more events → miss.


class TestNowFallthrough:
    def test_no_active_clock_returns_real_time(self):
        """Without a VirtualClock, now() falls through to datetime.now()."""
        before = datetime.now(timezone.utc)
        t = now()
        after = datetime.now(timezone.utc)
        assert before <= t <= after

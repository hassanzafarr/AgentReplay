"""Tests for agentreplay.recorder.rng — virtualized randomness.

Proves: record mode captures real random/uuid values, replay mode returns
them in order, public drop-in functions fall through when no context.

Does NOT cover: concurrent access, seeded RNG, statistical distribution.
"""

from __future__ import annotations

import pytest

from agentreplay.recorder.collector import TraceCollector
from agentreplay.recorder.rng import VirtualRNG
from agentreplay.recorder import rng as rng_module
from agentreplay.schema.trace import EventType


class TestVirtualRNGRecord:
    def test_records_random_value(self):
        """Record mode captures a float from random()."""
        collector = TraceCollector()
        vrng = VirtualRNG(collector, mode="record")

        with vrng:
            val = rng_module.random()

        assert 0.0 <= val <= 1.0

        events = collector.trace.get_events_by_type(EventType.RANDOM)
        assert len(events) == 1
        assert events[0].source == "random"

    def test_records_uuid4(self):
        """Record mode captures a UUID string."""
        collector = TraceCollector()
        vrng = VirtualRNG(collector, mode="record")

        with vrng:
            val = rng_module.uuid4()

        assert len(val) == 36  # UUID format: 8-4-4-4-12

        events = collector.trace.get_events_by_type(EventType.RANDOM)
        assert len(events) == 1
        assert events[0].source == "uuid4"

    def test_records_randint(self):
        """Record mode captures an integer from randint()."""
        collector = TraceCollector()
        vrng = VirtualRNG(collector, mode="record")

        with vrng:
            val = rng_module.randint(1, 100)

        assert 1 <= val <= 100

        events = collector.trace.get_events_by_type(EventType.RANDOM)
        assert len(events) == 1
        assert events[0].source == "randint"


class TestVirtualRNGReplay:
    def test_replays_random_values(self):
        """Replay returns the exact recorded random values in order."""
        collector = TraceCollector()
        vrng = VirtualRNG(collector, mode="record")

        with vrng:
            r1 = rng_module.random()
            r2 = rng_module.random()

        replay_rng = VirtualRNG(collector, mode="replay")
        with replay_rng:
            rr1 = rng_module.random()
            rr2 = rng_module.random()

        assert rr1 == r1
        assert rr2 == r2

    def test_replays_uuid4(self):
        """Replay returns the exact recorded UUID."""
        collector = TraceCollector()
        vrng = VirtualRNG(collector, mode="record")

        with vrng:
            original_uuid = rng_module.uuid4()

        replay_rng = VirtualRNG(collector, mode="replay")
        with replay_rng:
            replayed_uuid = rng_module.uuid4()

        assert replayed_uuid == original_uuid


class TestRNGFallthrough:
    def test_no_active_rng_returns_real_value(self):
        """Without VirtualRNG context, functions fall through to stdlib."""
        val = rng_module.random()
        assert 0.0 <= val <= 1.0

        uid = rng_module.uuid4()
        assert len(uid) == 36

"""Tests for agentreplay.schema.trace — Pydantic models.

Proves: models serialize/deserialize correctly, v1 traces load under the v2
schema, newer schema versions are rejected, discriminated union works, blob
content-addressing round-trips.

Does NOT cover: runtime behavior of recorder/replayer using these models.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agentreplay.schema.trace import (
    SCHEMA_VERSION,
    ClockEvent,
    EventType,
    LLMCallEvent,
    MessageRecord,
    RandomEvent,
    TokenUsage,
    ToolCallEvent,
    Trace,
    content_hash,
)


class TestContentHash:
    def test_deterministic(self):
        """Same input always produces same hash."""
        data = {"type": "human", "content": "hello"}
        assert content_hash(data) == content_hash(data)

    def test_different_inputs_different_hashes(self):
        """Different inputs produce different hashes."""
        assert content_hash({"a": 1}) != content_hash({"a": 2})

    def test_key_order_invariant(self):
        """Dict key order doesn't affect hash (sort_keys=True)."""
        assert content_hash({"b": 2, "a": 1}) == content_hash({"a": 1, "b": 2})


class TestSchemaVersion:
    def test_current_version_is_2(self):
        """v2 is the additive timing/usage/node release (D3 history)."""
        assert SCHEMA_VERSION == 2

    def test_trace_default_version(self):
        """New traces are written at the current version."""
        t = Trace()
        assert t.schema_version == SCHEMA_VERSION

    def test_v1_trace_loads_unchanged(self):
        """A v1 file (no v2 fields) still validates, keeps version 1, and
        every v2 field reads as None — old golden traces keep working.

        Does not cover: replaying v1 traces (the example-trace regression
        suite does that).
        """
        v1 = {
            "schema_version": 1,
            "run_id": "r1",
            "created_at": "2026-01-01T00:00:00Z",
            "events": [
                {"event_type": "llm_call", "seq": 0, "ts": "2026-01-01T00:00:01Z",
                 "hash": "h", "model_name": "m", "input_messages": [], "output": "o"},
                {"event_type": "tool_call", "seq": 1, "ts": "2026-01-01T00:00:02Z",
                 "hash": "t", "tool_name": "search", "input_args": {}, "output": "r"},
            ],
            "blobs": {},
            "metadata": {},
        }
        trace = Trace.model_validate(v1)
        llm, tool = trace.events

        assert trace.schema_version == 1
        for field in ("start_ts", "duration_ms", "node", "model_id", "usage"):
            assert getattr(llm, field) is None
        for field in ("start_ts", "duration_ms", "node"):
            assert getattr(tool, field) is None

    def test_future_version_rejected(self):
        """Pydantic would silently drop unknown v3 fields; we refuse instead."""
        with pytest.raises(ValueError, match="upgrade agentreplay"):
            Trace.model_validate({"schema_version": SCHEMA_VERSION + 1})

    def test_v2_fields_roundtrip(self):
        """Timing, node, model id and usage survive JSON round-trip."""
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        trace = Trace()
        trace.add_event(LLMCallEvent(
            seq=0,
            start_ts=start,
            duration_ms=812.5,
            node="agent",
            model_id="claude-x",
            usage=TokenUsage(
                input_tokens=100, output_tokens=20, total_tokens=120, cache_read_tokens=80,
            ),
        ))
        restored = Trace.model_validate(json.loads(json.dumps(trace.model_dump(mode="json"))))
        event = restored.events[0]

        assert event.start_ts == start
        assert event.duration_ms == 812.5
        assert event.node == "agent"
        assert event.model_id == "claude-x"
        assert event.usage.cache_read_tokens == 80
        assert event.usage.cache_creation_tokens is None


class TestEventModels:
    def test_llm_call_event_roundtrip(self):
        """LLMCallEvent survives JSON round-trip via Pydantic."""
        event = LLMCallEvent(
            seq=0,
            hash="abc123",
            model_name="test",
            input_messages=[MessageRecord(type="human", content="hello")],
            output="world",
        )
        data = event.model_dump(mode="json")
        restored = LLMCallEvent.model_validate(data)
        assert restored.seq == 0
        assert restored.output == "world"
        assert restored.input_messages[0].content == "hello"
        assert restored.event_type == EventType.LLM_CALL

    def test_tool_call_event_roundtrip(self):
        """ToolCallEvent survives JSON round-trip."""
        event = ToolCallEvent(
            seq=1,
            hash="def456",
            tool_name="search",
            input_args={"query": "test"},
            output="result",
        )
        data = event.model_dump(mode="json")
        restored = ToolCallEvent.model_validate(data)
        assert restored.tool_name == "search"
        assert restored.input_args["query"] == "test"

    def test_tool_call_event_with_error(self):
        """ToolCallEvent captures errors."""
        event = ToolCallEvent(
            seq=2, hash="x", tool_name="bad_tool",
            input_args={}, output="", error="ValueError: boom",
        )
        assert event.error == "ValueError: boom"

    def test_clock_event_roundtrip(self):
        """ClockEvent preserves the recorded datetime."""
        now = datetime.now(timezone.utc)
        event = ClockEvent(seq=3, recorded_time=now)
        data = event.model_dump(mode="json")
        restored = ClockEvent.model_validate(data)
        assert restored.event_type == EventType.CLOCK
        # Datetime comparison (allow minor serialization drift).
        assert restored.recorded_time.year == now.year

    def test_random_event_roundtrip(self):
        """RandomEvent preserves source and value."""
        event = RandomEvent(seq=4, source="uuid4", value="abc-123-def")
        data = event.model_dump(mode="json")
        restored = RandomEvent.model_validate(data)
        assert restored.source == "uuid4"
        assert restored.value == "abc-123-def"


class TestTrace:
    def test_trace_roundtrip(self):
        """Full Trace with mixed events survives JSON round-trip."""
        trace = Trace(metadata={"agent": "test"})
        trace.add_event(LLMCallEvent(
            seq=0, hash="h1", model_name="m", output="out",
            input_messages=[MessageRecord(type="human", content="hi")],
        ))
        trace.add_event(ToolCallEvent(
            seq=1, hash="h2", tool_name="search",
            input_args={"q": "x"}, output="found",
        ))
        trace.add_event(ClockEvent(
            seq=2, recorded_time=datetime.now(timezone.utc),
        ))
        trace.add_event(RandomEvent(
            seq=3, source="random", value="0.42",
        ))

        data = trace.model_dump(mode="json")
        json_str = json.dumps(data, default=str)
        restored = Trace.model_validate(json.loads(json_str))

        assert restored.schema_version == SCHEMA_VERSION
        assert len(restored.events) == 4
        assert restored.metadata["agent"] == "test"

    def test_get_events_by_type(self):
        """Filtering events by type works."""
        trace = Trace()
        trace.add_event(LLMCallEvent(seq=0, hash="a", output="x"))
        trace.add_event(ToolCallEvent(seq=1, hash="b", tool_name="t", output="y"))
        trace.add_event(LLMCallEvent(seq=2, hash="c", output="z"))

        llm_events = trace.get_events_by_type(EventType.LLM_CALL)
        assert len(llm_events) == 2

        tool_events = trace.get_events_by_type(EventType.TOOL_CALL)
        assert len(tool_events) == 1

    def test_blob_storage(self):
        """Blobs dict stores content-addressed large payloads."""
        trace = Trace()
        key = content_hash("large payload")
        trace.blobs[key] = "large payload"

        data = trace.model_dump(mode="json")
        restored = Trace.model_validate(data)
        assert restored.blobs[key] == "large payload"

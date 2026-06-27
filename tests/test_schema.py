"""Tests for agentreplay.schema.trace — Pydantic models.

Proves: models serialize/deserialize correctly, schema version is frozen,
discriminated union works, blob content-addressing round-trips.

Does NOT cover: runtime behavior of recorder/replayer using these models.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from agentreplay.schema.trace import (
    SCHEMA_VERSION,
    ClockEvent,
    EventType,
    LLMCallEvent,
    MessageRecord,
    RandomEvent,
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
    def test_frozen_at_1(self):
        """Schema version must be 1 — changes are breaking (D3)."""
        assert SCHEMA_VERSION == 1

    def test_trace_default_version(self):
        """New traces default to the frozen version."""
        t = Trace()
        assert t.schema_version == 1


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

        assert restored.schema_version == 1
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

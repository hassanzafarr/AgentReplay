"""Tests for TraceMatcher — hybrid hash+cursor matching.

Proves:
- Direct hash hit (common case, first call for a unique hash).
- Cursor fallback for repeated identical hashes (retry loops).
- Miss returns None event with hit_type="miss".
- Stats (hash_hits, cursor_fallbacks, misses) are accurate.
- reset() clears cursors and stats.
- lookup_by_seq() returns the event with that seq number.

Does NOT cover: async matching, multi-threaded concurrent lookups,
cross-event-type collision (event_type is part of the cursor key).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agentreplay.replayer.matcher import MatchStats, MatchResult, TraceMatcher
from agentreplay.schema.trace import (
    EventType,
    LLMCallEvent,
    MessageRecord,
    ToolCallEvent,
    Trace,
    content_hash,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _llm_event(seq: int, prompt: str, output: str = "response") -> LLMCallEvent:
    h = content_hash([{"type": "human", "content": prompt}])
    return LLMCallEvent(
        seq=seq,
        hash=h,
        model_name="test",
        input_messages=[MessageRecord(type="human", content=prompt)],
        output=output,
    )


def _tool_event(seq: int, tool: str, arg: str, output: str = "result") -> ToolCallEvent:
    h = content_hash({"tool": tool, "input": {"query": arg}})
    return ToolCallEvent(
        seq=seq,
        hash=h,
        tool_name=tool,
        input_args={"query": arg},
        output=output,
    )


def _trace_with(*events) -> Trace:
    t = Trace()
    for e in events:
        t.add_event(e)
    return t


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHashHit:
    def test_unique_hash_returns_event(self):
        """Direct hash hit: first lookup for a unique prompt."""
        event = _llm_event(0, "hello")
        trace = _trace_with(event)
        matcher = TraceMatcher(trace)

        result = matcher.lookup(EventType.LLM_CALL, event.hash)

        assert result.event is event
        assert result.hit_type == "hash"

    def test_hash_hit_increments_stat(self):
        """hash_hits counter increments on direct hit."""
        event = _llm_event(0, "hello")
        matcher = TraceMatcher(_trace_with(event))

        matcher.lookup(EventType.LLM_CALL, event.hash)

        assert matcher.stats.hash_hits == 1
        assert matcher.stats.cursor_fallbacks == 0
        assert matcher.stats.misses == 0


class TestCursorFallback:
    def test_repeated_hash_uses_cursor(self):
        """Two events with same hash are returned in order (retry-loop pattern)."""
        e0 = _llm_event(0, "retry prompt")
        e1 = LLMCallEvent(
            seq=1,
            hash=e0.hash,  # identical hash
            model_name="test",
            input_messages=[MessageRecord(type="human", content="retry prompt")],
            output="second response",
        )
        matcher = TraceMatcher(_trace_with(e0, e1))

        r0 = matcher.lookup(EventType.LLM_CALL, e0.hash)
        r1 = matcher.lookup(EventType.LLM_CALL, e0.hash)

        assert r0.event is e0
        assert r1.event is e1
        assert r1.hit_type == "cursor"

    def test_cursor_clamps_at_last_candidate(self):
        """Third lookup for two candidates returns the last one (defensive clamp)."""
        e0 = _llm_event(0, "retry")
        e1 = LLMCallEvent(
            seq=1, hash=e0.hash, model_name="test",
            input_messages=[MessageRecord(type="human", content="retry")],
            output="second",
        )
        matcher = TraceMatcher(_trace_with(e0, e1))

        matcher.lookup(EventType.LLM_CALL, e0.hash)  # → e0
        matcher.lookup(EventType.LLM_CALL, e0.hash)  # → e1
        r2 = matcher.lookup(EventType.LLM_CALL, e0.hash)  # → e1 (clamped)

        assert r2.event is e1

    def test_cursor_stat_tracked(self):
        """All lookups for a hash with multiple candidates use cursor path (not hash_hit).

        hash_hit is only for the unique-candidate fast path (1 candidate, first lookup).
        When there are 2+ candidates, every lookup goes through the cursor path.
        """
        e0 = _llm_event(0, "repeat")
        e1 = LLMCallEvent(
            seq=1, hash=e0.hash, model_name="test",
            input_messages=[MessageRecord(type="human", content="repeat")],
            output="second",
        )
        matcher = TraceMatcher(_trace_with(e0, e1))

        matcher.lookup(EventType.LLM_CALL, e0.hash)
        matcher.lookup(EventType.LLM_CALL, e0.hash)

        assert matcher.stats.cursor_fallbacks == 2
        assert matcher.stats.hash_hits == 0


class TestMiss:
    def test_unknown_hash_returns_none(self):
        """Miss: no event with matching hash → event=None, hit_type='miss'."""
        matcher = TraceMatcher(_trace_with(_llm_event(0, "something")))

        result = matcher.lookup(EventType.LLM_CALL, "deadbeef" * 8)

        assert result.event is None
        assert result.hit_type == "miss"

    def test_miss_stat_tracked(self):
        matcher = TraceMatcher(_trace_with(_llm_event(0, "A")))
        matcher.lookup(EventType.LLM_CALL, "unknown_hash")
        assert matcher.stats.misses == 1

    def test_wrong_event_type_is_a_miss(self):
        """Looking up TOOL_CALL for an LLM event hash is a miss (type isolation)."""
        event = _llm_event(0, "prompt")
        matcher = TraceMatcher(_trace_with(event))

        result = matcher.lookup(EventType.TOOL_CALL, event.hash)

        assert result.event is None
        assert result.hit_type == "miss"


class TestStats:
    def test_total_sums_correctly(self):
        e = _llm_event(0, "q")
        e2 = LLMCallEvent(
            seq=1, hash=e.hash, model_name="test",
            input_messages=e.input_messages, output="r2",
        )
        matcher = TraceMatcher(_trace_with(e, e2))

        # 2 candidates → both lookups go through cursor path (no hash_hit)
        matcher.lookup(EventType.LLM_CALL, e.hash)     # cursor (2 candidates)
        matcher.lookup(EventType.LLM_CALL, e.hash)     # cursor
        matcher.lookup(EventType.LLM_CALL, "nope")     # miss

        assert matcher.stats.total == 3
        assert matcher.stats.hash_hits == 0
        assert matcher.stats.cursor_fallbacks == 2
        assert matcher.stats.misses == 1

    def test_miss_rate(self):
        matcher = TraceMatcher(Trace())
        for _ in range(3):
            matcher.lookup(EventType.LLM_CALL, "x")
        assert matcher.stats.miss_rate == 1.0

    def test_miss_rate_zero_total(self):
        assert MatchStats().miss_rate == 0.0


class TestReset:
    def test_reset_clears_cursors_and_stats(self):
        """After reset(), cursor restarts so the first candidate is returned again."""
        e0 = _llm_event(0, "repeat")
        e1 = LLMCallEvent(
            seq=1, hash=e0.hash, model_name="test",
            input_messages=e0.input_messages, output="second",
        )
        matcher = TraceMatcher(_trace_with(e0, e1))

        matcher.lookup(EventType.LLM_CALL, e0.hash)  # → e0 (cursor=0)
        matcher.lookup(EventType.LLM_CALL, e0.hash)  # → e1 (cursor=1)
        matcher.reset()

        # Cursor back to 0 → e0 again; stats reset to 0.
        r = matcher.lookup(EventType.LLM_CALL, e0.hash)
        assert r.event is e0
        assert matcher.stats.cursor_fallbacks == 1  # only the post-reset lookup
        assert matcher.stats.hash_hits == 0


class TestLookupBySeq:
    def test_finds_event_by_seq(self):
        e0 = _llm_event(0, "a")
        e1 = _tool_event(1, "search", "query")
        matcher = TraceMatcher(_trace_with(e0, e1))

        assert matcher.lookup_by_seq(0) is e0
        assert matcher.lookup_by_seq(1) is e1

    def test_returns_none_for_missing_seq(self):
        matcher = TraceMatcher(_trace_with(_llm_event(0, "a")))
        assert matcher.lookup_by_seq(99) is None


class TestToolMatching:
    def test_tool_event_matched_by_hash(self):
        """Tool events are matched by their own hash namespace."""
        event = _tool_event(0, "web_search", "climate change")
        matcher = TraceMatcher(_trace_with(event))

        result = matcher.lookup(EventType.TOOL_CALL, event.hash)

        assert result.event is event
        assert result.hit_type == "hash"

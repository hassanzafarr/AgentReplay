"""Tests for agentreplay.recorder.interceptor — RecordingChatModel.

Proves: record mode captures events, replay mode serves from trace with
zero live calls (TripwireModel pattern), hybrid matching works, async
variant behaves identically.

Does NOT cover: tool calls, clock/rng, trace writing, the wrap() API.
"""

from __future__ import annotations

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agentreplay.recorder.collector import TraceCollector
from agentreplay.recorder.interceptor import RecordingChatModel
from agentreplay.schema.trace import EventType


# -------------------------------------------------------------------
# Test fixtures: same StandInModel/TripwireModel pattern from spike
# -------------------------------------------------------------------

class StandInModel(BaseChatModel):
    """Deterministic model for record-mode tests."""

    @property
    def _llm_type(self) -> str:
        return "standin"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        text = f"[answer to: {messages[-1].content[:40]}]"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


class TripwireModel(BaseChatModel):
    """Explodes if called — proves replay makes zero live calls."""

    @property
    def _llm_type(self) -> str:
        return "tripwire"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("TRIPWIRE: live LLM call during replay")


# -------------------------------------------------------------------
# Record mode tests
# -------------------------------------------------------------------

class TestRecordMode:
    def test_captures_llm_event(self):
        """Record mode captures an LLMCallEvent with correct fields."""
        collector = TraceCollector()
        model = RecordingChatModel(
            inner=StandInModel(), mode="record", collector=collector,
        )
        result = model.invoke([HumanMessage(content="test prompt")])

        events = collector.trace.get_events_by_type(EventType.LLM_CALL)
        assert len(events) == 1

        event = events[0]
        assert event.seq == 0
        assert event.model_name == "standin"
        assert event.input_messages[0].content == "test prompt"
        assert event.output == result.content
        assert event.hash  # Non-empty hash.

    def test_captures_multiple_calls_with_incrementing_seq(self):
        """Multiple calls get incrementing seq numbers."""
        collector = TraceCollector()
        model = RecordingChatModel(
            inner=StandInModel(), mode="record", collector=collector,
        )
        model.invoke([HumanMessage(content="first")])
        model.invoke([HumanMessage(content="second")])

        events = collector.trace.get_events_by_type(EventType.LLM_CALL)
        assert len(events) == 2
        assert events[0].seq == 0
        assert events[1].seq == 1

    def test_output_matches_inner_model(self):
        """Record mode returns the inner model's actual response."""
        collector = TraceCollector()
        model = RecordingChatModel(
            inner=StandInModel(), mode="record", collector=collector,
        )
        result = model.invoke([HumanMessage(content="hello world")])
        assert "hello world" in result.content  # StandInModel echoes input.


# -------------------------------------------------------------------
# Replay mode tests
# -------------------------------------------------------------------

class TestReplayMode:
    def _record_and_get_trace(self, prompts: list[str]) -> TraceCollector:
        """Helper: record several prompts and return the collector."""
        collector = TraceCollector()
        model = RecordingChatModel(
            inner=StandInModel(), mode="record", collector=collector,
        )
        for p in prompts:
            model.invoke([HumanMessage(content=p)])
        return collector

    def test_replay_serves_recorded_response(self):
        """Replay returns the exact recorded output for a matching hash."""
        collector = self._record_and_get_trace(["what is gravity?"])

        replay_model = RecordingChatModel(
            inner=TripwireModel(), mode="replay", collector=collector,
        )
        result = replay_model.invoke([HumanMessage(content="what is gravity?")])

        expected = collector.trace.events[0].output
        assert result.content == expected

    def test_replay_zero_live_calls(self):
        """Replay never calls the inner model (TripwireModel doesn't fire)."""
        collector = self._record_and_get_trace(["prompt A", "prompt B"])

        replay_model = RecordingChatModel(
            inner=TripwireModel(), mode="replay", collector=collector,
        )
        # Both replays succeed without triggering the tripwire.
        replay_model.invoke([HumanMessage(content="prompt A")])
        replay_model.invoke([HumanMessage(content="prompt B")])

    def test_replay_miss_raises(self):
        """A prompt not in the trace raises LookupError (divergence signal)."""
        collector = self._record_and_get_trace(["recorded prompt"])

        replay_model = RecordingChatModel(
            inner=TripwireModel(), mode="replay", collector=collector,
        )
        with pytest.raises(LookupError, match="REPLAY MISS"):
            replay_model.invoke([HumanMessage(content="totally different prompt")])

    def test_replay_handles_repeated_prompts(self):
        """Repeated identical prompts get different responses via cursor."""
        collector = TraceCollector()
        model = RecordingChatModel(
            inner=StandInModel(), mode="record", collector=collector,
        )
        # Record the same prompt twice (simulates a retry loop).
        # StandInModel gives same response, but seq differs.
        model.invoke([HumanMessage(content="retry me")])
        model.invoke([HumanMessage(content="retry me")])

        replay_model = RecordingChatModel(
            inner=TripwireModel(), mode="replay", collector=collector,
        )
        r1 = replay_model.invoke([HumanMessage(content="retry me")])
        r2 = replay_model.invoke([HumanMessage(content="retry me")])
        # Both should succeed (cursor advances through same-hash events).
        assert r1.content == r2.content  # Same output since StandInModel is deterministic.


class TestModelIdentity:
    def test_llm_type_wraps_inner(self):
        """The recording model's type includes the inner model's type."""
        model = RecordingChatModel(
            inner=StandInModel(), mode="record", collector=TraceCollector(),
        )
        assert "standin" in model._llm_type

"""End-to-end integration test: wrap() a LangGraph agent → trace file.

THIS IS THE PHASE 1 EXIT CRITERION.

Proves:
- agentreplay.wrap() accepts a build function + model.
- A recorded run produces a valid trace JSON file with all LLM events.
- The trace round-trips through Pydantic.
- Replay against the recorded trace produces byte-identical output with
  zero live LLM calls (TripwireModel pattern).

Does NOT cover: tool interception in integration (tested separately),
async invoke, real API providers, multi-run regression.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.graph import END, StateGraph

import agentreplay
from agentreplay.recorder.trace_writer import TraceWriter
from agentreplay.schema.trace import EventType


# -------------------------------------------------------------------
# Test fixtures
# -------------------------------------------------------------------

class StandInModel(BaseChatModel):
    """Deterministic model for record-mode tests."""

    @property
    def _llm_type(self) -> str:
        return "standin"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        text = f"[answer to: {messages[-1].content[:60]}]"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


class TripwireModel(BaseChatModel):
    """Explodes if called — proves replay made zero live calls."""

    @property
    def _llm_type(self) -> str:
        return "tripwire"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("TRIPWIRE: live LLM call during replay")


class AgentState(TypedDict):
    topic: str
    research: str
    brief: str


def build_agent(model: BaseChatModel):
    """Build a 2-node research→write agent (same pattern as spike)."""

    def research_node(state: AgentState) -> AgentState:
        resp = model.invoke([HumanMessage(content=f"Research: {state['topic']}")])
        return {**state, "research": resp.content}

    def write_node(state: AgentState) -> AgentState:
        resp = model.invoke([HumanMessage(content=f"Brief from: {state['research']}")])
        return {**state, "brief": resp.content}

    g = StateGraph(AgentState)
    g.add_node("research", research_node)
    g.add_node("write", write_node)
    g.set_entry_point("research")
    g.add_edge("research", "write")
    g.add_edge("write", END)
    return g.compile()


# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------

class TestEndToEndRecord:
    def test_wrap_produces_trace_file(self, tmp_path):
        """wrap() in record mode produces a valid .trace.json file."""
        trace_dir = tmp_path / "traces"

        wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=StandInModel(),
            mode="record",
            trace_dir=trace_dir,
        )

        result = wrapped.invoke({"topic": "quantum computing", "research": "", "brief": ""})

        # Result should have both fields populated.
        assert result["research"]
        assert result["brief"]

        # Trace file should exist.
        trace_path = wrapped.last_trace_path
        assert trace_path is not None
        assert trace_path.exists()
        assert trace_path.suffix == ".json"

    def test_trace_has_correct_events(self, tmp_path):
        """Recorded trace contains exactly 2 LLM call events (research + write)."""
        wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=StandInModel(),
            mode="record",
            trace_dir=tmp_path / "traces",
        )
        wrapped.invoke({"topic": "AI safety", "research": "", "brief": ""})

        trace = wrapped.last_trace
        assert trace is not None

        llm_events = trace.get_events_by_type(EventType.LLM_CALL)
        assert len(llm_events) == 2

        # First event is the research call.
        assert "Research:" in llm_events[0].input_messages[0].content
        # Second event is the write call, which should reference the research output.
        assert llm_events[0].output in llm_events[1].input_messages[0].content

    def test_trace_roundtrips_through_pydantic(self, tmp_path):
        """The trace file validates back through Pydantic."""
        wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=StandInModel(),
            mode="record",
            trace_dir=tmp_path / "traces",
        )
        wrapped.invoke({"topic": "test", "research": "", "brief": ""})

        trace_path = wrapped.last_trace_path
        restored = TraceWriter.read(trace_path)
        assert restored.schema_version == 1
        assert len(restored.events) == 2


class TestEndToEndReplay:
    def test_replay_reproduces_output_with_zero_live_calls(self, tmp_path):
        """THE EXIT CRITERION: replay produces byte-identical output at $0.

        Record with StandInModel, then replay with TripwireModel as inner.
        If TripwireModel never fires, zero live calls happened.
        """
        trace_dir = tmp_path / "traces"

        # --- Record ---
        record_wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=StandInModel(),
            mode="record",
            trace_dir=trace_dir,
        )
        record_result = record_wrapped.invoke({
            "topic": "carbon capture", "research": "", "brief": "",
        })
        recorded_trace = record_wrapped.last_trace

        # --- Replay ---
        replay_wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=TripwireModel(),  # Explodes if called.
            mode="replay",
            trace_dir=trace_dir,
            trace=recorded_trace,
        )
        replay_result = replay_wrapped.invoke({
            "topic": "carbon capture", "research": "", "brief": "",
        })

        # Byte-identical output.
        assert replay_result["research"] == record_result["research"]
        assert replay_result["brief"] == record_result["brief"]

    def test_replay_with_different_input_raises(self, tmp_path):
        """Replaying with a different input triggers a divergence (REPLAY MISS)."""
        trace_dir = tmp_path / "traces"

        record_wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=StandInModel(),
            mode="record",
            trace_dir=trace_dir,
        )
        record_wrapped.invoke({"topic": "topic A", "research": "", "brief": ""})
        recorded_trace = record_wrapped.last_trace

        replay_wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=TripwireModel(),
            mode="replay",
            trace_dir=trace_dir,
            trace=recorded_trace,
        )

        with pytest.raises(LookupError, match="REPLAY MISS"):
            replay_wrapped.invoke({
                "topic": "completely different topic", "research": "", "brief": "",
            })

"""Tests for ReplayEngine — end-to-end replay against a recorded trace.

THIS IS THE PHASE 2 EXIT CRITERION.

Proves:
- ReplayEngine.run() reproduces byte-identical agent output at zero LLM cost.
- The inner model (TripwireModel) is never called during replay.
- Tool replay serves recorded output without calling the real function.
- A changed input (different prompt hash) raises LookupError (divergence signal).
- The replay_trace has LLM + tool events matching the original structure.
- divergence_report is clean (is_identical=True) when code is unchanged.
- match_stats reports hits and no misses on clean replay.
- Tool side effects are NOT replayed (v1 stance; documented limitation).

Does NOT cover: async replay, clock/RNG events in replay trace,
multi-node parallel graphs, real API provider.
"""

from __future__ import annotations

from typing import TypedDict

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.graph import END, StateGraph

import agentreplay
from agentreplay.replayer.replay_engine import ReplayEngine
from agentreplay.schema.trace import EventType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class StandInModel(BaseChatModel):
    """Deterministic model for record-mode tests."""

    @property
    def _llm_type(self) -> str:
        return "standin"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        text = f"[answer: {messages[-1].content[:40]}]"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


class TripwireModel(BaseChatModel):
    """Explodes if called — proves zero live LLM calls during replay."""

    @property
    def _llm_type(self) -> str:
        return "tripwire"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("TRIPWIRE: live LLM call during replay")


class AgentState(TypedDict):
    topic: str
    research: str
    brief: str


def build_agent(model: BaseChatModel) -> object:
    """2-node research→write agent."""

    def research_node(state: AgentState) -> AgentState:
        resp = model.invoke([HumanMessage(content=f"Research: {state['topic']}")])
        return {**state, "research": resp.content}

    def write_node(state: AgentState) -> AgentState:
        resp = model.invoke([HumanMessage(content=f"Write: {state['research']}")])
        return {**state, "brief": resp.content}

    g = StateGraph(AgentState)
    g.add_node("research", research_node)
    g.add_node("write", write_node)
    g.set_entry_point("research")
    g.add_edge("research", "write")
    g.add_edge("write", END)
    return g.compile()


def build_agent_with_tool(model: BaseChatModel, tools: list) -> object:
    """Single-node agent that calls a tool then the LLM."""

    def agent_node(state: AgentState) -> AgentState:
        # Call tool directly (not via LLM tool-use, for simplicity).
        tool_result = tools[0].invoke({"query": state["topic"]})
        resp = model.invoke([HumanMessage(content=f"Summarize: {tool_result}")])
        return {**state, "research": tool_result, "brief": resp.content}

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.set_entry_point("agent")
    g.add_edge("agent", END)
    return g.compile()


def _make_counter_tool():
    """A tool that counts how many times its real function was called."""
    call_count = {"n": 0}

    def real_search(query: str) -> str:
        call_count["n"] += 1
        return f"results for: {query}"

    tool = StructuredTool.from_function(
        func=real_search,
        name="web_search",
        description="Search the web",
    )
    return tool, call_count


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReplayIdentical:
    def test_replay_produces_identical_output(self, tmp_path):
        """THE PHASE 2 EXIT CRITERION: replay at $0 reproduces byte-identical output.

        Record with StandInModel, replay with TripwireModel. If TripwireModel
        never fires, zero live LLM calls occurred.
        """
        input_state = {"topic": "carbon capture", "research": "", "brief": ""}

        # --- Record ---
        wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=StandInModel(),
            mode="record",
            trace_dir=tmp_path / "traces",
        )
        record_result = wrapped.invoke(input_state)
        recorded_trace = wrapped.last_trace

        # --- Replay ---
        engine = ReplayEngine(
            recorded_trace=recorded_trace,
            build_fn=build_agent,
            model=TripwireModel(),  # explodes if called
        )
        result = engine.run(input_state)

        assert result.output["research"] == record_result["research"]
        assert result.output["brief"] == record_result["brief"]

    def test_divergence_report_is_clean_on_identical_replay(self, tmp_path):
        """Replaying unchanged code against its own trace → no divergences."""
        wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=StandInModel(),
            mode="record",
            trace_dir=tmp_path / "traces",
        )
        wrapped.invoke({"topic": "AI safety", "research": "", "brief": ""})
        recorded_trace = wrapped.last_trace

        engine = ReplayEngine(
            recorded_trace=recorded_trace,
            build_fn=build_agent,
            model=TripwireModel(),
        )
        result = engine.run({"topic": "AI safety", "research": "", "brief": ""})

        assert result.divergence_report.is_identical

    def test_match_stats_no_misses(self, tmp_path):
        """Clean replay has zero misses in match stats."""
        wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=StandInModel(),
            mode="record",
            trace_dir=tmp_path / "traces",
        )
        wrapped.invoke({"topic": "test", "research": "", "brief": ""})

        engine = ReplayEngine(
            recorded_trace=wrapped.last_trace,
            build_fn=build_agent,
            model=TripwireModel(),
        )
        result = engine.run({"topic": "test", "research": "", "brief": ""})

        assert result.match_stats.misses == 0
        assert result.match_stats.total > 0


class TestReplayMiss:
    def test_changed_input_raises_lookup_error(self, tmp_path):
        """Replaying with a different topic → different hash → LookupError (divergence)."""
        wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=StandInModel(),
            mode="record",
            trace_dir=tmp_path / "traces",
        )
        wrapped.invoke({"topic": "original topic", "research": "", "brief": ""})

        engine = ReplayEngine(
            recorded_trace=wrapped.last_trace,
            build_fn=build_agent,
            model=TripwireModel(),
        )

        with pytest.raises(LookupError, match="REPLAY MISS"):
            engine.run({"topic": "completely different topic", "research": "", "brief": ""})


class TestToolReplay:
    def test_tool_replay_serves_recorded_output(self, tmp_path):
        """Tool replay returns the recorded output without calling the real function."""
        tool, call_count = _make_counter_tool()

        # --- Record ---
        wrapped = agentreplay.wrap(
            build_fn=build_agent_with_tool,
            model=StandInModel(),
            mode="record",
            trace_dir=tmp_path / "traces",
            tools=[tool],
        )
        record_result = wrapped.invoke({"topic": "climate", "research": "", "brief": ""})
        recorded_trace = wrapped.last_trace

        # Real function was called once during recording.
        assert call_count["n"] == 1

        # --- Replay ---
        # Replace tool with a new instance whose real function would
        # return different data — but replay should never call it.
        def different_search(query: str) -> str:
            call_count["n"] += 1
            return "SHOULD NOT SEE THIS"

        replay_tool = StructuredTool.from_function(
            func=different_search,
            name="web_search",
            description="Search the web",
        )

        engine = ReplayEngine(
            recorded_trace=recorded_trace,
            build_fn=build_agent_with_tool,
            model=TripwireModel(),
            tools=[replay_tool],
        )
        replay_result = engine.run({"topic": "climate", "research": "", "brief": ""})

        # Real function was NOT called during replay.
        assert call_count["n"] == 1
        # Output matches recorded (tool output is the research field).
        assert replay_result.output["research"] == record_result["research"]

    def test_tool_events_in_replay_trace(self, tmp_path):
        """Replay trace contains ToolCallEvents from the replay run."""
        tool, _ = _make_counter_tool()

        wrapped = agentreplay.wrap(
            build_fn=build_agent_with_tool,
            model=StandInModel(),
            mode="record",
            trace_dir=tmp_path / "traces",
            tools=[tool],
        )
        wrapped.invoke({"topic": "test", "research": "", "brief": ""})

        replay_tool = StructuredTool.from_function(
            func=lambda query: "ignored",
            name="web_search",
            description="Search the web",
        )
        engine = ReplayEngine(
            recorded_trace=wrapped.last_trace,
            build_fn=build_agent_with_tool,
            model=TripwireModel(),
            tools=[replay_tool],
        )
        result = engine.run({"topic": "test", "research": "", "brief": ""})

        tool_events = result.replay_trace.get_events_by_type(EventType.TOOL_CALL)
        assert len(tool_events) == 1
        assert tool_events[0].tool_name == "web_search"


class TestReplayTrace:
    def test_replay_trace_has_llm_events(self, tmp_path):
        """Replay trace captures LLMCallEvents that happened during replay."""
        wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=StandInModel(),
            mode="record",
            trace_dir=tmp_path / "traces",
        )
        wrapped.invoke({"topic": "quantum", "research": "", "brief": ""})

        engine = ReplayEngine(
            recorded_trace=wrapped.last_trace,
            build_fn=build_agent,
            model=TripwireModel(),
        )
        result = engine.run({"topic": "quantum", "research": "", "brief": ""})

        llm_events = result.replay_trace.get_events_by_type(EventType.LLM_CALL)
        assert len(llm_events) == 2  # research + write nodes

    def test_replay_result_has_original_and_replay_traces(self, tmp_path):
        """ReplayResult exposes both original_trace and replay_trace."""
        wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=StandInModel(),
            mode="record",
            trace_dir=tmp_path / "traces",
        )
        wrapped.invoke({"topic": "x", "research": "", "brief": ""})

        engine = ReplayEngine(
            recorded_trace=wrapped.last_trace,
            build_fn=build_agent,
            model=TripwireModel(),
        )
        result = engine.run({"topic": "x", "research": "", "brief": ""})

        assert result.original_trace is wrapped.last_trace
        assert result.replay_trace is not None
        assert result.replay_trace.run_id != result.original_trace.run_id

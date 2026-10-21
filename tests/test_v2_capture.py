"""Tests for schema v2 capture — timing, node, model id, token usage.

Proves: the LLM interceptor records ``start_ts``/``duration_ms``, the served
model id (response metadata first, configured model as fallback) and the
provider's token usage; the tool wrapper records timing even when the tool
raises; inside a real LangGraph run every LLM/tool event carries the node
that made it (sync and async graphs); replay events carry node + timing but
never token usage; differing timing/usage never counts as a divergence.

Does NOT cover: real provider response shapes (no API key in this env — the
fake models emit LangChain's standard ``usage_metadata`` /
``response_metadata``), or timing of parallel nodes.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.graph import END, StateGraph

import agentreplay
from agentreplay.recorder.collector import TraceCollector
from agentreplay.recorder.interceptor import RecordingChatModel
from agentreplay.recorder.tool_wrapper import wrap_tool
from agentreplay.replayer.divergence import diff_traces
from agentreplay.replayer.replay_engine import ReplayEngine
from agentreplay.schema.trace import (
    EventType,
    LLMCallEvent,
    TokenUsage,
    ToolCallEvent,
    Trace,
)


# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------

class MeteredModel(BaseChatModel):
    """Reports usage and the served model id the way LangChain providers do."""

    model: str = "claude-configured"
    served: str | None = "claude-served-2026"

    @property
    def _llm_type(self) -> str:
        return "metered"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        time.sleep(0.01)
        msg = AIMessage(
            content=f"[answer to: {messages[-1].content[:40]}]",
            usage_metadata={
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "input_token_details": {"cache_read": 80},
            },
            response_metadata={"model_name": self.served} if self.served else {},
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])


class PlainModel(BaseChatModel):
    """Reports neither usage nor a model id."""

    @property
    def _llm_type(self) -> str:
        return "plain"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])


class TripwireModel(BaseChatModel):
    """Explodes if called — proves replay made zero live calls."""

    @property
    def _llm_type(self) -> str:
        return "tripwire"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("TRIPWIRE: live LLM call during replay")


def _make_tool(fail: bool = False) -> StructuredTool:
    """Fresh tool per test: wrap_tool mutates the tool in place."""

    def lookup(query: str) -> str:
        time.sleep(0.01)
        if fail:
            raise ValueError("boom")
        return f"order status for {query}"

    return StructuredTool.from_function(func=lookup, name="lookup_order", description="Look up")


class State(TypedDict):
    query: str
    found: str
    answer: str


def build_sync(model: BaseChatModel, tools: list):
    """lookup node calls the tool, answer node calls the LLM."""

    def lookup(state: State) -> State:
        return {**state, "found": tools[0].invoke({"query": state["query"]})}

    def answer(state: State) -> State:
        resp = model.invoke([HumanMessage(content=f"Answer using: {state['found']}")])
        return {**state, "answer": resp.content}

    g = StateGraph(State)
    g.add_node("lookup", lookup)
    g.add_node("answer", answer)
    g.set_entry_point("lookup")
    g.add_edge("lookup", "answer")
    g.add_edge("answer", END)
    return g.compile()


def build_async(model: BaseChatModel, tools: list):
    """Async twin of build_sync (exercises ainvoke paths)."""

    async def lookup(state: State) -> State:
        return {**state, "found": await tools[0].ainvoke({"query": state["query"]})}

    async def answer(state: State) -> State:
        resp = await model.ainvoke([HumanMessage(content=f"Answer using: {state['found']}")])
        return {**state, "answer": resp.content}

    g = StateGraph(State)
    g.add_node("lookup", lookup)
    g.add_node("answer", answer)
    g.set_entry_point("lookup")
    g.add_edge("lookup", "answer")
    g.add_edge("answer", END)
    return g.compile()


INPUT = {"query": "order-42", "found": "", "answer": ""}


def _record(model: BaseChatModel) -> LLMCallEvent:
    collector = TraceCollector()
    RecordingChatModel(inner=model, mode="record", collector=collector).invoke(
        [HumanMessage(content="hi")],
    )
    return collector.trace.get_events_by_type(EventType.LLM_CALL)[0]


# -------------------------------------------------------------------
# LLM interceptor
# -------------------------------------------------------------------

class TestLLMCapture:
    def test_records_timing(self):
        """start_ts is a tz-aware wall-clock start; duration is measured."""
        event = _record(MeteredModel())

        assert event.start_ts is not None and event.start_ts.tzinfo is not None
        assert event.start_ts <= event.ts
        assert event.duration_ms is not None and event.duration_ms >= 5

    def test_model_id_prefers_served_model(self):
        """The response names the model that actually answered (aliases)."""
        assert _record(MeteredModel()).model_id == "claude-served-2026"

    def test_model_id_falls_back_to_configured_model(self):
        assert _record(MeteredModel(served=None)).model_id == "claude-configured"

    def test_usage_from_usage_metadata(self):
        usage = _record(MeteredModel()).usage

        assert usage == TokenUsage(
            input_tokens=100, output_tokens=20, total_tokens=120, cache_read_tokens=80,
        )

    def test_nothing_reported_means_none(self):
        """No usage/model info → None, never zeros that look like real data."""
        event = _record(PlainModel())

        assert event.usage is None
        assert event.model_id is None
        assert event.node is None  # not inside a graph

    async def test_async_path_records_v2_fields(self):
        collector = TraceCollector()
        model = RecordingChatModel(inner=MeteredModel(), mode="record", collector=collector)
        await model.ainvoke([HumanMessage(content="hi")])
        event = collector.trace.get_events_by_type(EventType.LLM_CALL)[0]

        assert event.duration_ms is not None
        assert event.model_id == "claude-served-2026"
        assert event.usage.output_tokens == 20


# -------------------------------------------------------------------
# Tool wrapper
# -------------------------------------------------------------------

class TestToolCapture:
    def test_records_timing(self):
        collector = TraceCollector()
        wrap_tool(_make_tool(), collector).invoke({"query": "x"})
        event = collector.trace.get_events_by_type(EventType.TOOL_CALL)[0]

        assert event.start_ts is not None
        assert event.duration_ms is not None and event.duration_ms >= 5

    def test_records_timing_when_tool_raises(self):
        """Failed calls are often the slow ones; timing must survive errors."""
        collector = TraceCollector()
        tool = wrap_tool(_make_tool(fail=True), collector)
        try:
            tool.invoke({"query": "x"})
        except ValueError:
            pass
        event = collector.trace.get_events_by_type(EventType.TOOL_CALL)[0]

        assert event.error == "ValueError: boom"
        assert event.duration_ms is not None


# -------------------------------------------------------------------
# LangGraph node attribution
# -------------------------------------------------------------------

class TestNodeCapture:
    def _events(self, trace: Trace) -> tuple[ToolCallEvent, LLMCallEvent]:
        tool = trace.get_events_by_type(EventType.TOOL_CALL)[0]
        llm = trace.get_events_by_type(EventType.LLM_CALL)[0]
        return tool, llm

    def test_sync_graph_events_carry_node(self, tmp_path):
        wrapped = agentreplay.wrap(
            build_sync, MeteredModel(), tools=[_make_tool()], trace_dir=tmp_path,
        )
        wrapped.invoke(INPUT)
        tool, llm = self._events(wrapped.last_trace)

        assert tool.node == "lookup"
        assert llm.node == "answer"

    async def test_async_graph_events_carry_node(self, tmp_path):
        """Async nodes reach the tool via ainvoke (thread executor) — the
        node must still come through the copied context."""
        wrapped = agentreplay.wrap(
            build_async, MeteredModel(), tools=[_make_tool()], trace_dir=tmp_path,
        )
        await wrapped.ainvoke(INPUT)
        tool, llm = self._events(wrapped.last_trace)

        assert tool.node == "lookup"
        assert llm.node == "answer"


# -------------------------------------------------------------------
# Replay + divergence
# -------------------------------------------------------------------

class TestReplayV2:
    def test_replay_events_have_node_and_timing_but_no_usage(self, tmp_path):
        """Replay spends no tokens, so its events must not claim usage —
        exported replays would otherwise show up as real cost."""
        wrapped = agentreplay.wrap(
            build_sync, MeteredModel(), tools=[_make_tool()], trace_dir=tmp_path,
        )
        wrapped.invoke(INPUT)

        result = ReplayEngine(
            wrapped.last_trace, build_sync, TripwireModel(), tools=[_make_tool()],
        ).run(INPUT)
        tool = result.replay_trace.get_events_by_type(EventType.TOOL_CALL)[0]
        llm = result.replay_trace.get_events_by_type(EventType.LLM_CALL)[0]

        assert (tool.node, llm.node) == ("lookup", "answer")
        assert tool.duration_ms is not None and llm.duration_ms is not None
        assert llm.usage is None and llm.model_id is None
        # Recorded durations (~10ms sleeps) differ from replay (~0ms): still identical.
        assert result.divergence_report.is_identical

    def test_metric_differences_are_not_divergences(self):
        """Timing, usage and model id change every run; only behaviour counts."""
        def trace(duration: float, tokens: int, model: str) -> Trace:
            t = Trace()
            t.add_event(LLMCallEvent(
                seq=0, hash="h", output="same",
                start_ts=datetime.now(timezone.utc) - timedelta(seconds=duration),
                duration_ms=duration * 1000, model_id=model,
                usage=TokenUsage(input_tokens=tokens, output_tokens=1, total_tokens=tokens + 1),
            ))
            t.add_event(ToolCallEvent(seq=1, hash="t", tool_name="x", duration_ms=duration))
            return t

        report = diff_traces(trace(0.5, 100, "claude-a"), trace(3.0, 900, "claude-b"))
        assert report.is_identical

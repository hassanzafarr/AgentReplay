"""Tests for the agentreplay pytest plugin.

Uses pytester (pytest's plugin testing fixture) to run isolated pytest
sessions and verify collection + pass/fail outcomes.

Key design: pytest_collect_file is called only for files inside the rootdir
that pytest scans via testpaths. So tests write trace files into pytester's
temp dir and set testpaths = traces in the ini.

Proves:
- Plugin collects .trace.json files when agentreplay_traces + agentreplay_agent
  are configured AND traces are on a testpath.
- A trace replayed against unchanged code → test PASSES.
- A trace replayed against changed agent code (different prompt) → test FAILS.
- Missing config → no trace collection (graceful no-op).
- wrap().invoke() auto-stores _agentreplay_input in trace metadata.

Does NOT cover: model factory spec, async replay via plugin, parallel execution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.graph import END, StateGraph

import agentreplay
from agentreplay.recorder.trace_writer import TraceWriter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class StandInModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "standin"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        text = f"[answer: {messages[-1].content[:40]}]"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


class AgentState(TypedDict):
    topic: str
    research: str
    brief: str


def build_agent_original(model: BaseChatModel):
    def node(state: AgentState) -> AgentState:
        resp = model.invoke([HumanMessage(content=f"Research: {state['topic']}")])
        return {**state, "research": resp.content, "brief": resp.content}

    g = StateGraph(AgentState)
    g.add_node("research", node)
    g.set_entry_point("research")
    g.add_edge("research", END)
    return g.compile()


def _record_trace(trace_dir: Path, topic: str = "climate") -> Path:
    """Record a trace and return the .trace.json path."""
    wrapped = agentreplay.wrap(
        build_fn=build_agent_original,
        model=StandInModel(),
        mode="record",
        trace_dir=trace_dir,
    )
    wrapped.invoke({"topic": topic, "research": "", "brief": ""})
    return wrapped.last_trace_path


def _copy_trace_to_pytester(pytester, trace_path: Path) -> Path:
    """Copy a trace file into pytester's traces/ dir and return the new path."""
    dest_dir = pytester.path / "traces"
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / trace_path.name
    dest.write_text(trace_path.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


# Build function string shared across pytester tests.
_BUILD_FN_SOURCE = """
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph, END
from typing import TypedDict

class AgentState(TypedDict):
    topic: str
    research: str
    brief: str

def build_agent(model):
    def node(state):
        resp = model.invoke([HumanMessage(content=f"Research: {state['topic']}")])
        return {**state, "research": resp.content, "brief": resp.content}
    g = StateGraph(AgentState)
    g.add_node("research", node)
    g.set_entry_point("research")
    g.add_edge("research", END)
    return g.compile()
"""

_CHANGED_BUILD_FN_SOURCE = """
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph, END
from typing import TypedDict

class AgentState(TypedDict):
    topic: str
    research: str
    brief: str

def build_agent(model):
    def node(state):
        # CHANGED: different prompt — hash will miss, causing a LookupError
        resp = model.invoke([HumanMessage(content=f"DIFFERENT PROMPT: {state['topic']}")])
        return {**state, "research": resp.content, "brief": resp.content}
    g = StateGraph(AgentState)
    g.add_node("research", node)
    g.set_entry_point("research")
    g.add_edge("research", END)
    return g.compile()
"""


# ---------------------------------------------------------------------------
# Tests — metadata auto-storage
# ---------------------------------------------------------------------------

class TestInputAutoStore:
    def test_agentreplay_input_stored_in_metadata(self, tmp_path):
        """wrap().invoke() stores input in trace.metadata['_agentreplay_input']."""
        trace_path = _record_trace(tmp_path / "traces")
        trace = TraceWriter.read(trace_path)
        assert "_agentreplay_input" in trace.metadata
        assert trace.metadata["_agentreplay_input"]["topic"] == "climate"

    def test_user_metadata_preserved(self, tmp_path):
        """Custom metadata merges with _agentreplay_input, not overwritten."""
        wrapped = agentreplay.wrap(
            build_fn=build_agent_original,
            model=StandInModel(),
            mode="record",
            trace_dir=tmp_path / "traces",
            metadata={"env": "ci"},
        )
        wrapped.invoke({"topic": "test", "research": "", "brief": ""})
        trace = wrapped.last_trace
        assert trace.metadata["env"] == "ci"
        assert "_agentreplay_input" in trace.metadata


# ---------------------------------------------------------------------------
# Tests — plugin collection
# ---------------------------------------------------------------------------

class TestPluginCollection:
    def test_collects_trace_files_when_configured(self, pytester, tmp_path):
        """Plugin collects .trace.json when ini is set and trace is in testpaths."""
        trace_path = _record_trace(tmp_path / "traces")
        _copy_trace_to_pytester(pytester, trace_path)

        pytester.makepyfile(my_agent=_BUILD_FN_SOURCE)
        pytester.makeini("""
[pytest]
testpaths = traces
agentreplay_traces = traces
agentreplay_agent = my_agent:build_agent
""")

        result = pytester.runpytest("-p", "agentreplay.integrations.pytest_plugin", "-v")
        result.assert_outcomes(passed=1)

    def test_no_collection_without_config(self, pytester, tmp_path):
        """Without agentreplay_traces/agent ini options, no trace tests run."""
        trace_path = _record_trace(tmp_path / "traces")
        _copy_trace_to_pytester(pytester, trace_path)

        pytester.makeini("""
[pytest]
testpaths = traces
""")

        result = pytester.runpytest("-p", "agentreplay.integrations.pytest_plugin", "-v")
        result.assert_outcomes(passed=0, failed=0)


# ---------------------------------------------------------------------------
# Tests — pass/fail outcomes
# ---------------------------------------------------------------------------

class TestPluginPassFail:
    def test_unchanged_agent_passes(self, pytester, tmp_path):
        """Identical agent code → replay matches recording → test passes."""
        trace_path = _record_trace(tmp_path / "traces", topic="climate")
        _copy_trace_to_pytester(pytester, trace_path)

        pytester.makepyfile(my_agent=_BUILD_FN_SOURCE)
        pytester.makeini("""
[pytest]
testpaths = traces
agentreplay_traces = traces
agentreplay_agent = my_agent:build_agent
""")

        result = pytester.runpytest("-p", "agentreplay.integrations.pytest_plugin", "-v")
        result.assert_outcomes(passed=1)

    def test_changed_prompt_fails(self, pytester, tmp_path):
        """Changed prompt → hash miss → LookupError → test fails."""
        trace_path = _record_trace(tmp_path / "traces", topic="climate")
        _copy_trace_to_pytester(pytester, trace_path)

        pytester.makepyfile(my_agent=_CHANGED_BUILD_FN_SOURCE)
        pytester.makeini("""
[pytest]
testpaths = traces
agentreplay_traces = traces
agentreplay_agent = my_agent:build_agent
""")

        result = pytester.runpytest("-p", "agentreplay.integrations.pytest_plugin", "-v")
        result.assert_outcomes(failed=1)

    def test_failure_output_contains_failed_marker(self, pytester, tmp_path):
        """Failed trace test shows FAILED in output."""
        trace_path = _record_trace(tmp_path / "traces")
        _copy_trace_to_pytester(pytester, trace_path)

        pytester.makepyfile(my_agent=_CHANGED_BUILD_FN_SOURCE)
        pytester.makeini("""
[pytest]
testpaths = traces
agentreplay_traces = traces
agentreplay_agent = my_agent:build_agent
""")

        result = pytester.runpytest("-p", "agentreplay.integrations.pytest_plugin", "-v")
        assert "FAILED" in "\n".join(result.outlines)

    def test_multiple_traces_independent(self, pytester, tmp_path):
        """Two identical trace files → two independent passing tests."""
        for topic in ["climate", "ai-safety"]:
            trace_path = _record_trace(tmp_path / "traces", topic=topic)
            _copy_trace_to_pytester(pytester, trace_path)

        pytester.makepyfile(my_agent=_BUILD_FN_SOURCE)
        pytester.makeini("""
[pytest]
testpaths = traces
agentreplay_traces = traces
agentreplay_agent = my_agent:build_agent
""")

        result = pytester.runpytest("-p", "agentreplay.integrations.pytest_plugin", "-v")
        result.assert_outcomes(passed=2)

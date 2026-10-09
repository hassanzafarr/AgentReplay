"""End-to-end AgentReplay demo — the whole story in one command.

    python -m examples.research_agent.demo

No API key needed. Walks through the three things AgentReplay is for:

1. RECORD   a live agent run into a trace file.
2. REPLAY   it offline against a model that raises if it is ever called —
            proving the replay made zero live LLM calls ($0).
3. CATCH    a regression: change one prompt, and AgentReplay flags exactly
            which call diverged instead of silently passing.

Traces are written to a temporary directory so the repo stays clean.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

import agentreplay
from agentreplay.cli import _ensure_utf8_stdout
from examples.research_agent.agent import AgentState, StandInModel, build_agent

INPUT = {"topic": "carbon capture and storage", "research": "", "brief": ""}


class TripwireModel(BaseChatModel):
    """A model that fails loudly if called. Used to prove replay is offline."""

    @property
    def _llm_type(self) -> str:
        return "tripwire"

    def _generate(self, *args, **kwargs):
        raise RuntimeError("TRIPWIRE: a live LLM call was made during replay")


def build_agent_v2(model: BaseChatModel):
    """Same agent with one 'harmless' prompt edit — the kind that breaks prod."""

    def research_node(state: AgentState) -> AgentState:
        prompt = f"Research this topic briefly: {state['topic']}"  # was "thoroughly"
        return {**state, "research": model.invoke([HumanMessage(content=prompt)]).content}

    def write_node(state: AgentState) -> AgentState:
        prompt = f"Write a concise brief based on this research:\n\n{state['research']}"
        return {**state, "brief": model.invoke([HumanMessage(content=prompt)]).content}

    g = StateGraph(AgentState)
    g.add_node("research", research_node)
    g.add_node("write", write_node)
    g.set_entry_point("research")
    g.add_edge("research", "write")
    g.add_edge("write", END)
    return g.compile()


def _record(build_fn, trace_dir: Path) -> Path:
    wrapped = agentreplay.wrap(
        build_fn=build_fn, model=StandInModel(), mode="record", trace_dir=trace_dir
    )
    wrapped.invoke(INPUT)
    return wrapped.last_trace_path


def _banner(text: str) -> None:
    print(f"\n{'=' * 64}\n  {text}\n{'=' * 64}")


def main() -> None:
    _ensure_utf8_stdout()
    trace_dir = Path(tempfile.mkdtemp(prefix="agentreplay-demo-"))

    _banner("1. RECORD a live run")
    baseline_path = _record(build_agent, trace_dir)
    baseline = agentreplay.TraceWriter.read(baseline_path)
    print(f"Recorded {len(baseline.events)} events -> {baseline_path.name}")
    for e in baseline.events:
        print(f"  [{e.seq}] {e.event_type.value:<9} hash={e.hash[:12]}")

    _banner("2. REPLAY offline against a tripwire model")
    result = agentreplay.ReplayEngine(
        recorded_trace=baseline, build_fn=build_agent, model=TripwireModel()
    ).run(INPUT)
    stats = result.match_stats
    print(f"Tripwire fired: no  ->  0 live LLM calls, $0 spent")
    print(f"Matcher: {stats.hash_hits} hash hits, {stats.misses} misses")
    print(f"Final state identical to recording: {result.output['brief'] == _final_brief(baseline)}")
    print(result.divergence_report.format_report())

    _banner("3. CATCH a regression: one word changed in a prompt")
    try:
        agentreplay.ReplayEngine(
            recorded_trace=baseline, build_fn=build_agent_v2, model=TripwireModel()
        ).run(INPUT)
        print("Replay passed (unexpected)")
    except LookupError as exc:
        print(f"Replay stopped at the changed call:\n  {exc}")

    print("\nDiffing the baseline trace against a fresh run of v2:")
    candidate = agentreplay.TraceWriter.read(_record(build_agent_v2, trace_dir))
    print(agentreplay.diff_traces(baseline, candidate).format_report())

    print(f"\nTraces kept in {trace_dir} — open them in the dashboard to explore.")


def _final_brief(trace) -> str:
    return trace.events[-1].output


if __name__ == "__main__":
    main()

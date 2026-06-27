"""Throwaway example agent for the Phase 0 spike.

A minimal two-node LangGraph that calls a chat model twice along its path.
Two LLM calls (not one) is deliberate: it lets the spike prove that
call->response matching keeps the calls in the right order, which a
single-call agent could never exercise.

The model is injected, not constructed here, so the spike can swap a
recording stand-in (record mode) or a tripwire (replay mode) for the
same graph without touching agent code. That injection seam is the
whole reason interception is cheap.
"""

from __future__ import annotations

from typing import TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph


class ResearchState(TypedDict):
    """State threaded through the graph. Kept tiny on purpose."""

    topic: str
    research: str
    brief: str


def build_agent(model: BaseChatModel):
    """Build a 2-node research->brief graph bound to `model`.

    Node `research` asks the model to gather facts; node `write` asks it to
    turn those facts into a brief. Each node makes exactly one LLM call, so
    a full run produces a deterministic 2-call sequence we can record.
    """

    def research_node(state: ResearchState) -> ResearchState:
        resp = model.invoke([HumanMessage(content=f"Research the topic: {state['topic']}")])
        return {**state, "research": resp.content}

    def write_node(state: ResearchState) -> ResearchState:
        resp = model.invoke(
            [HumanMessage(content=f"Write a brief from these facts: {state['research']}")]
        )
        return {**state, "brief": resp.content}

    g = StateGraph(ResearchState)
    g.add_node("research", research_node)
    g.add_node("write", write_node)
    g.set_entry_point("research")
    g.add_edge("research", "write")
    g.add_edge("write", END)
    return g.compile()

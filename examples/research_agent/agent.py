"""Research & Brief Generator — dogfood demo for AgentReplay.

A simple 2-node LangGraph agent: research node → write node.
Instrumented with agentreplay.wrap() so every run is captured as a trace.

Run record.py once to generate example traces, then run pytest to
see the regression suite in action.

    python -m examples.research_agent.record
    pytest examples/research_agent/ -v
"""

from __future__ import annotations

from typing import TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.graph import END, StateGraph


class AgentState(TypedDict):
    topic: str
    research: str
    brief: str


def build_agent(model: BaseChatModel):
    """Build the research→write LangGraph app with the given model.

    This is the function registered with the pytest plugin::

        agentreplay_agent = "examples.research_agent.agent:build_agent"
    """

    def research_node(state: AgentState) -> AgentState:
        prompt = f"Research this topic thoroughly: {state['topic']}"
        resp = model.invoke([HumanMessage(content=prompt)])
        return {**state, "research": resp.content}

    def write_node(state: AgentState) -> AgentState:
        prompt = f"Write a concise brief based on this research:\n\n{state['research']}"
        resp = model.invoke([HumanMessage(content=prompt)])
        return {**state, "brief": resp.content}

    g = StateGraph(AgentState)
    g.add_node("research", research_node)
    g.add_node("write", write_node)
    g.set_entry_point("research")
    g.add_edge("research", "write")
    g.add_edge("write", END)
    return g.compile()


# ---------------------------------------------------------------------------
# Stub model for recording without a real API key
# ---------------------------------------------------------------------------

class StandInModel(BaseChatModel):
    """Deterministic model for recording example traces without an API key."""

    @property
    def _llm_type(self) -> str:
        return "standin"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        prompt = messages[-1].content[:80]
        text = f"[Recorded response for: {prompt}]"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

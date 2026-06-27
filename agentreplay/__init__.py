"""AgentReplay — deterministic record/replay for LangGraph agents.

Public API::

    import agentreplay

    # Record a run
    wrapped = agentreplay.wrap(build_my_agent, model, mode="record")
    result = wrapped.invoke({"topic": "carbon capture"})

    # Virtual clock/rng for agent code
    t = agentreplay.now()
    r = agentreplay.random()
    u = agentreplay.uuid4()
"""

from agentreplay.integrations.langgraph import wrap, WrappedAgent
from agentreplay.recorder.clock import now
from agentreplay.recorder.rng import random, randint, uuid4
from agentreplay.recorder.trace_writer import TraceWriter
from agentreplay.schema.trace import Trace

__all__ = [
    "wrap",
    "WrappedAgent",
    "now",
    "random",
    "randint",
    "uuid4",
    "Trace",
    "TraceWriter",
]

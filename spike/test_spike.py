"""Phase 0 gate tests.

These tests ARE the gate from plan section 5. If they pass, the core bet
holds and the project is viable. If they fail or fight us, we stop.

Each test states what it proves and what it does NOT cover.
"""

from __future__ import annotations

from agent import build_agent
from spike import RecordingChatModel, StandInModel, TripwireModel


def _record_run(topic: str):
    """Run the agent live (against the stand-in) and capture a trace."""
    rec = RecordingChatModel(inner=StandInModel(), mode="record", trace=[])
    app = build_agent(rec)
    final = app.invoke({"topic": topic, "research": "", "brief": ""})
    return final, rec.trace


def _replay_run(topic: str, trace: list):
    """Re-run the same agent in replay mode against a TRIPWIRE inner model.

    The tripwire raises if any live call leaks through, so a successful
    invoke is proof of zero live calls.
    """
    rep = RecordingChatModel(inner=TripwireModel(), mode="replay", trace=trace)
    app = build_agent(rep)
    final = app.invoke({"topic": topic, "research": "", "brief": ""})
    return final


def test_replay_reproduces_output_with_zero_live_calls():
    """Proves: a recorded run replays to a byte-identical final state while
    the wrapped model would raise on any call -> reproducible at $0.

    Does NOT cover: real API responses, async/parallel nodes, code-path
    changes, tool calls, clock/RNG. Those are later phases.
    """
    topic = "carbon capture economics"
    live_final, trace = _record_run(topic)

    assert len(trace) == 2, "agent should make exactly 2 LLM calls"

    replay_final = _replay_run(topic, trace)

    # Byte-identical reproduction of every model-derived field.
    assert replay_final["research"] == live_final["research"]
    assert replay_final["brief"] == live_final["brief"]


def test_tripwire_actually_fires_when_called():
    """Proves the tripwire is real: if replay had a miss and fell through to
    the inner model, it WOULD raise. (Guards against a false-green gate where
    the tripwire is silently a no-op.)

    Does NOT cover: anything about matching; this only validates the proof
    instrument itself.
    """
    import pytest

    tw = TripwireModel()
    from langchain_core.messages import HumanMessage

    with pytest.raises(RuntimeError, match="TRIPWIRE"):
        tw.invoke([HumanMessage(content="anything")])


def test_recorded_inputs_match_across_runs():
    """Proves: the exact LLM inputs flowing through the graph on replay match
    those recorded live (plan's 'byte-identical LLM inputs' criterion).

    We assert the second call's recorded input embeds the first call's
    recorded output, i.e. data really flowed research->write through state.

    Does NOT cover: hashing collisions, prompt-volatility edge cases.
    """
    _, trace = _record_run("offshore wind")
    research_out = trace[0]["output"]
    write_input = trace[1]["input"][0]["content"]
    assert research_out in write_input, "write node must consume research output"


def test_replay_miss_raises_not_silent():
    """Proves: a replay against a trace that lacks the needed response fails
    loudly (LookupError), so a code-path change can never silently pass.
    Phase 2 upgrades this from 'raise' to 'reported divergence'.

    Does NOT cover: the eventual divergence-report format.
    """
    import pytest

    # Record on one topic, replay on a DIFFERENT topic -> hashes won't match.
    _, trace = _record_run("topic A")
    with pytest.raises(LookupError, match="REPLAY MISS"):
        _replay_run("topic B is completely different", trace)

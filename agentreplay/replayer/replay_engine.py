"""Replay engine — re-runs an agent against a recorded trace at zero LLM cost.

The engine feeds all impure inputs (LLM responses, tool outputs, clock, RNG)
from the recorded trace back into the agent, then diffs the resulting event
sequence to detect divergences (Decision D4).

Usage::

    from agentreplay.replayer.replay_engine import ReplayEngine

    engine = ReplayEngine(
        recorded_trace=trace,
        build_fn=build_my_agent,
        model=TripwireModel(),  # never actually called
    )
    result = engine.run({"topic": "carbon capture"})
    print(result.divergence_report.format_report())

The ``model`` arg is needed by the graph builder but is never invoked —
pass any ``BaseChatModel`` instance (e.g., a ``TripwireModel`` that
raises if called, to prove zero live API calls).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from functools import wraps
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool, StructuredTool

from agentreplay.recorder.clock import VirtualClock
from agentreplay.recorder.collector import TraceCollector
from agentreplay.recorder.interceptor import _hash_messages, _messages_to_records
from agentreplay.recorder.rng import VirtualRNG
from agentreplay.recorder.tool_wrapper import _normalize_args, _safe_serialize
from agentreplay.replayer.divergence import DivergenceReport, diff_traces
from agentreplay.replayer.matcher import MatchStats, TraceMatcher
from agentreplay.schema.trace import (
    EventType,
    LLMCallEvent,
    ToolCallEvent,
    Trace,
    content_hash,
)


@dataclass
class ReplayResult:
    """Outcome of a replay run.

    ``replay_trace`` contains LLM + tool events that actually occurred during
    the replay. Clock/RNG events are not re-captured (they are always
    deterministic). Diff ``replay_trace`` against ``original_trace`` to find
    what changed.
    """

    original_trace: Trace
    replay_trace: Trace
    output: Any
    match_stats: MatchStats
    divergence_report: DivergenceReport


class ReplayEngine:
    """Re-runs an agent against a recorded trace, producing a divergence report.

    Replay works in three steps:
    1. Serve all LLM responses from the recorded trace (zero API calls).
    2. Serve all tool outputs from the recorded trace (no side effects).
    3. Serve clock/RNG values from the recorded trace (deterministic).

    A new trace of what actually happened is produced and diffed against the
    original to surface structural and tool-call divergences.
    """

    def __init__(
        self,
        recorded_trace: Trace,
        build_fn: Any,
        model: BaseChatModel,
        *,
        tools: list[BaseTool] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._recorded = recorded_trace
        self._build_fn = build_fn
        self._model = model
        self._tools = tools or []
        self._metadata = metadata or {}

    def run(self, input: dict[str, Any]) -> ReplayResult:
        """Replay the recorded trace against current code.

        Raises ``LookupError`` when the new code makes a call the recorded
        trace never captured — that IS the divergence signal.
        """
        matcher = TraceMatcher(self._recorded)
        replay_collector = TraceCollector(metadata=self._metadata)

        # LLM: serve from recorded trace, capture new events to replay_collector.
        replay_model = _ReplayChatModel(
            inner=self._model,
            matcher=matcher,
            replay_collector=replay_collector,
        )

        # Build graph with the replay model.
        sig = inspect.signature(self._build_fn)
        if len(sig.parameters) >= 2:
            # build_fn needs tools — use provided tools or auto-stub from trace.
            tools = self._tools if self._tools else _make_stub_tools(self._recorded)
            replay_tools = [
                _wrap_tool_for_replay(t, matcher, replay_collector)
                for t in tools
            ]
            app = self._build_fn(replay_model, replay_tools)
        else:
            app = self._build_fn(replay_model)

        # Clock + RNG: use existing VirtualClock/VirtualRNG in replay mode.
        # They need a collector whose trace contains the recorded events.
        passthrough = TraceCollector()
        passthrough._trace = self._recorded

        clock = VirtualClock(passthrough, mode="replay")
        rng = VirtualRNG(passthrough, mode="replay")

        with clock, rng:
            output = app.invoke(input)

        divergence_report = diff_traces(self._recorded, replay_collector.trace)

        return ReplayResult(
            original_trace=self._recorded,
            replay_trace=replay_collector.trace,
            output=output,
            match_stats=matcher.stats,
            divergence_report=divergence_report,
        )


# ---------------------------------------------------------------------------
# Internal — replay-mode chat model
# ---------------------------------------------------------------------------

class _ReplayChatModel(BaseChatModel):
    """Serves LLM responses from a TraceMatcher and records to the replay collector.

    The inner model is never invoked. It is stored only so ``_llm_type``
    reports correctly and the graph builder receives a valid ``BaseChatModel``.
    """

    inner: BaseChatModel
    matcher: TraceMatcher
    replay_collector: TraceCollector

    model_config = {"arbitrary_types_allowed": True}

    @property
    def _llm_type(self) -> str:
        return f"replay({self.inner._llm_type})"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        input_hash = _hash_messages(messages)
        result = self.matcher.lookup(EventType.LLM_CALL, input_hash)

        if result.event is None:
            raise LookupError(
                f"REPLAY MISS: no recorded LLM response for hash "
                f"{input_hash[:12]}… — divergence from recorded trace."
            )

        event: LLMCallEvent = result.event
        output_text = event.output
        # Resolve blob reference if the output was stored separately.
        if event.output_blob_key and event.output_blob_key in self.matcher.trace.blobs:
            output_text = self.matcher.trace.blobs[event.output_blob_key]

        # Capture this call to the replay trace.
        new_event = LLMCallEvent(
            seq=self.replay_collector.next_seq(),
            hash=input_hash,
            model_name=self.inner._llm_type,
            input_messages=_messages_to_records(messages),
            output=output_text,
            kwargs={k: str(v) for k, v in kwargs.items()},
        )
        self.replay_collector.add_event(new_event)

        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=output_text))]
        )

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


# ---------------------------------------------------------------------------
# Internal — replay-mode tool wrapper
# ---------------------------------------------------------------------------

def _wrap_tool_for_replay(
    tool: BaseTool,
    matcher: TraceMatcher,
    replay_collector: TraceCollector,
) -> BaseTool:
    """Return *tool* patched to serve recorded output instead of calling real function."""
    if not isinstance(tool, StructuredTool):
        return _wrap_invoke_for_replay(tool, matcher, replay_collector)

    if tool.func is not None:
        original_func = tool.func

        @wraps(original_func)
        def replay_func(*args: Any, **kwargs: Any) -> Any:
            input_args = _normalize_args(args, kwargs)
            tool_hash = content_hash({"tool": tool.name, "input": input_args})

            match_result = matcher.lookup(EventType.TOOL_CALL, tool_hash)
            if match_result.event is None:
                raise LookupError(
                    f"REPLAY MISS: no recorded output for tool '{tool.name}' "
                    f"with hash {tool_hash[:12]}…"
                )

            recorded_event: ToolCallEvent = match_result.event
            replay_collector.add_event(ToolCallEvent(
                seq=replay_collector.next_seq(),
                hash=tool_hash,
                tool_name=tool.name,
                input_args=input_args,
                output=recorded_event.output,
                error=recorded_event.error,
            ))
            return recorded_event.output

        tool.func = replay_func

    return tool


def _make_stub_tools(trace: Trace) -> list[BaseTool]:
    """Auto-generate minimal stub tools from recorded ToolCallEvents.

    Used when the build_fn accepts tools but the caller didn't provide any.
    The stubs have the right names (so the LLM can reference them) but their
    functions are immediately replaced by _wrap_tool_for_replay, so they
    never execute.
    """
    from agentreplay.schema.trace import EventType

    tool_names = {
        e.tool_name
        for e in trace.events
        if e.event_type == EventType.TOOL_CALL
    }
    stubs = []
    for name in sorted(tool_names):
        # func is a placeholder — it is overwritten by _wrap_tool_for_replay.
        stub = StructuredTool.from_function(
            func=lambda **kwargs: "",
            name=name,
            description=f"Auto-stub for '{name}' (replay mode — never called)",
        )
        stubs.append(stub)
    return stubs


def _wrap_invoke_for_replay(
    tool: BaseTool,
    matcher: TraceMatcher,
    replay_collector: TraceCollector,
) -> BaseTool:
    """Fallback for non-StructuredTool: patch public invoke()."""
    original_invoke = tool.invoke

    def replay_invoke(input: Any, **kwargs: Any) -> Any:
        input_args = {"input": _safe_serialize(input)}
        tool_hash = content_hash({"tool": tool.name, "input": input_args})

        match_result = matcher.lookup(EventType.TOOL_CALL, tool_hash)
        if match_result.event is None:
            raise LookupError(
                f"REPLAY MISS: no recorded output for tool '{tool.name}' "
                f"with hash {tool_hash[:12]}…"
            )

        recorded_event: ToolCallEvent = match_result.event
        replay_collector.add_event(ToolCallEvent(
            seq=replay_collector.next_seq(),
            hash=tool_hash,
            tool_name=tool.name,
            input_args=input_args,
            output=recorded_event.output,
            error=recorded_event.error,
        ))
        return recorded_event.output

    tool.invoke = replay_invoke  # type: ignore[assignment]
    return tool

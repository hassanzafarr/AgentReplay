"""LangGraph integration — the ``wrap()`` API.

This is the only thing most users touch::

    import agentreplay

    app = agentreplay.wrap(
        my_langgraph_app,
        model=my_model,
        mode="record",
        trace_dir="./traces",
    )
    result = app.invoke({"topic": "carbon capture"})
    # → trace file written to ./traces/<run_id>.trace.json

Design: v1 uses explicit model/tool passing (not auto-discovery) because
walking a compiled LangGraph's internals is fragile and version-dependent.
Explicit passing is simple, reliable, and matches the "scope small"
philosophy. Auto-discovery can be added in v2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool

from agentreplay.recorder.clock import VirtualClock
from agentreplay.recorder.collector import TraceCollector
from agentreplay.recorder.interceptor import RecordingChatModel
from agentreplay.recorder.rng import VirtualRNG
from agentreplay.recorder.tool_wrapper import wrap_tool
from agentreplay.recorder.trace_writer import TraceWriter


class WrappedAgent:
    """Thin wrapper that adds record/replay lifecycle around a LangGraph app.

    Not a LangGraph ``CompiledStateGraph`` — it delegates to one. This is
    intentional: we don't want to re-implement the graph protocol, just
    wrap the invoke/ainvoke entry points.
    """

    def __init__(
        self,
        build_fn: Any,
        model: BaseChatModel,
        *,
        mode: str = "record",
        trace_dir: str | Path = "./traces",
        tools: list[BaseTool] | None = None,
        metadata: dict[str, Any] | None = None,
        trace: Any | None = None,
    ) -> None:
        """
        Args:
            build_fn: A callable ``(model, tools?) -> compiled_graph`` that
                builds the LangGraph app with injected model/tools.
            model: The real ``BaseChatModel`` to wrap.
            mode: ``"record"`` or ``"replay"``.
            trace_dir: Directory for trace JSON files.
            tools: Optional list of ``BaseTool`` instances to instrument.
            metadata: Arbitrary metadata to include in the trace.
            trace: For replay mode — a pre-loaded ``Trace`` object.
        """
        self._build_fn = build_fn
        self._original_model = model
        self._mode = mode
        self._trace_dir = Path(trace_dir)
        self._tools = tools or []
        self._metadata = metadata or {}
        self._trace = trace

    def invoke(self, input: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Run the agent with recording or replay active."""
        from agentreplay.schema.trace import Trace

        # Set up collector.
        if self._mode == "replay" and self._trace is not None:
            collector = TraceCollector(metadata=self._metadata)
            # Load the pre-existing trace into the collector for replay lookups.
            collector._trace = self._trace
        else:
            collector = TraceCollector(metadata=self._metadata)

        # Wrap the model.
        recording_model = RecordingChatModel(
            inner=self._original_model,
            mode=self._mode,
            collector=collector,
        )

        # Wrap tools.
        wrapped_tools = [wrap_tool(t, collector) for t in self._tools]

        # Build the graph with wrapped model (and optionally wrapped tools).
        import inspect
        sig = inspect.signature(self._build_fn)
        if len(sig.parameters) >= 2:
            app = self._build_fn(recording_model, wrapped_tools)
        else:
            app = self._build_fn(recording_model)

        # Activate virtual clock and RNG.
        clock = VirtualClock(collector, mode=self._mode)
        rng = VirtualRNG(collector, mode=self._mode)

        with clock, rng:
            result = app.invoke(input, **kwargs)

        # Write trace to disk (record mode only).
        if self._mode == "record":
            writer = TraceWriter(self._trace_dir)
            path = writer.write(collector.trace)
            # Stash path for caller access.
            self._last_trace_path = path
            self._last_trace = collector.trace

        return result

    async def ainvoke(self, input: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Async version of invoke."""
        from agentreplay.schema.trace import Trace

        if self._mode == "replay" and self._trace is not None:
            collector = TraceCollector(metadata=self._metadata)
            collector._trace = self._trace
        else:
            collector = TraceCollector(metadata=self._metadata)

        recording_model = RecordingChatModel(
            inner=self._original_model,
            mode=self._mode,
            collector=collector,
        )

        wrapped_tools = [wrap_tool(t, collector) for t in self._tools]

        import inspect
        sig = inspect.signature(self._build_fn)
        if len(sig.parameters) >= 2:
            app = self._build_fn(recording_model, wrapped_tools)
        else:
            app = self._build_fn(recording_model)

        clock = VirtualClock(collector, mode=self._mode)
        rng = VirtualRNG(collector, mode=self._mode)

        with clock, rng:
            result = await app.ainvoke(input, **kwargs)

        if self._mode == "record":
            writer = TraceWriter(self._trace_dir)
            path = writer.write(collector.trace)
            self._last_trace_path = path
            self._last_trace = collector.trace

        return result

    @property
    def last_trace_path(self) -> Path | None:
        """Path to the most recently written trace file."""
        return getattr(self, "_last_trace_path", None)

    @property
    def last_trace(self) -> Any | None:
        """The most recently recorded ``Trace`` object."""
        return getattr(self, "_last_trace", None)


def wrap(
    build_fn: Any,
    model: BaseChatModel,
    *,
    mode: str = "record",
    trace_dir: str | Path = "./traces",
    tools: list[BaseTool] | None = None,
    metadata: dict[str, Any] | None = None,
    trace: Any | None = None,
) -> WrappedAgent:
    """Wrap a LangGraph agent for recording or replay.

    This is the primary public API::

        import agentreplay

        wrapped = agentreplay.wrap(
            build_fn=build_my_agent,   # (model) -> compiled graph
            model=ChatAnthropic(...),
            mode="record",
        )
        result = wrapped.invoke({"topic": "carbon capture"})
        print(wrapped.last_trace_path)  # ./traces/<run_id>.trace.json

    Args:
        build_fn: A callable that takes a ``BaseChatModel`` (and optionally
            a list of tools) and returns a compiled LangGraph app.
        model: The real chat model to use (wrapped transparently).
        mode: ``"record"`` to capture a live run, ``"replay"`` to serve
            from a pre-recorded trace.
        trace_dir: Where to write trace files (record mode).
        tools: LangChain tools to instrument.
        metadata: Arbitrary metadata stored in the trace.
        trace: A ``Trace`` object for replay mode.

    Returns:
        A ``WrappedAgent`` with ``.invoke()`` and ``.ainvoke()`` methods.
    """
    return WrappedAgent(
        build_fn=build_fn,
        model=model,
        mode=mode,
        trace_dir=trace_dir,
        tools=tools,
        metadata=metadata,
        trace=trace,
    )

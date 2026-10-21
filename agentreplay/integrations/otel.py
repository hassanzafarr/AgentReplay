"""OpenTelemetry export — turn a recorded ``Trace`` into OTel spans.

Why export *after* the run, from the trace, instead of instrumenting live:

- The trace is already the complete record of a run, so exporting it needs
  zero recorder changes and works on every trace ever written — including
  golden traces in CI.
- Export stays entirely outside the record/replay path. Network I/O there
  would break the offline, $0 replay guarantee.
- Any OTLP backend can receive it: Jaeger, Grafana Tempo, Datadog,
  Honeycomb, and Langfuse (which ingests OTLP natively).

Span layout::

    agentreplay.run                      root, one per trace
    ├── <node>                           one per consecutive run of a LangGraph node (v2)
    │   ├── chat <model>                 one per LLMCallEvent
    │   └── execute_tool <tool_name>     one per ToolCallEvent
    └── span events: clock, random       instant draws, not operations

Attribute names follow the OTel GenAI semantic conventions (``gen_ai.*``)
where they exist, plus ``langfuse.*`` hints Langfuse uses to pick the
observation type and render input/output. Other backends ignore them.

Timing: schema v2 events carry a measured ``start_ts`` + ``duration_ms``.
v1 events have only ``ts`` (when the call *completed*), so their start is
inferred as the previous event's ``ts`` — accurate for sequential agents, an
over-estimate for parallel nodes. Every call span says which it is via
``agentreplay.timing.inferred``. v1 traces have no node, so their calls hang
directly off the root.

Privacy: prompts, completions, tool args/results and error messages are NOT
exported unless ``include_content=True``. This mirrors the OTel GenAI
default of not capturing message content — exporting ships it to a third
party.

OpenTelemetry is an optional dependency (``pip install 'agentreplay[otel]'``);
it is imported lazily so the core package never requires it.
"""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Sequence

from agentreplay.schema.trace import (
    ClockEvent,
    LLMCallEvent,
    RandomEvent,
    ToolCallEvent,
    Trace,
)

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SpanExporter
    from opentelemetry.trace import Span, Tracer

INSTALL_HINT = (
    "OpenTelemetry export needs optional packages: "
    "pip install 'agentreplay[otel]'"
)

ROOT_SPAN_NAME = "agentreplay.run"

LANGFUSE_DEFAULT_HOST = "https://cloud.langfuse.com"

# LangChain message types -> GenAI semconv roles.
_ROLE_MAP = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def export_trace(
    trace: Trace,
    *,
    tracer_provider: "TracerProvider | None" = None,
    include_content: bool = False,
    environment: str | None = None,
    shift_to_now: bool = False,
) -> str:
    """Emit *trace* as OpenTelemetry spans and return the OTel trace id (hex).

    Args:
        trace: A recorded (or replayed) AgentReplay trace.
        tracer_provider: Where spans go. Defaults to the global provider, so
            apps that already configure OTel need no extra setup.
        include_content: Export prompts, completions, tool args/results and
            error messages. Off by default (see module docstring: privacy).
        environment: Set as ``deployment.environment.name`` on every span.
            Tag replay/CI exports (e.g. ``"replay"``) so they never mix with
            production traffic in dashboards.
        shift_to_now: Move the whole run so it starts at export time, keeping
            every relative offset and duration. Needed for old (e.g. golden)
            traces: backends with data retention, such as Langfuse Cloud,
            silently drop spans older than their retention window. The
            original time stays in ``agentreplay.recorded_at``.

    The caller owns the provider's lifecycle: flush it (``force_flush()``)
    before the process exits or batched spans may be lost.
    """
    otel_trace = _require_otel()
    from opentelemetry.trace import SpanKind, Status, StatusCode

    provider = tracer_provider or otel_trace.get_tracer_provider()
    tracer = provider.get_tracer("agentreplay", _package_version())

    common: dict[str, Any] = {"agentreplay.run_id": trace.run_id}
    if environment:
        common["deployment.environment.name"] = environment

    events = sorted(trace.events, key=lambda e: e.seq)
    recorded_start = _to_ns(trace.created_at)
    offset = time.time_ns() - recorded_start if shift_to_now else 0
    run_start = recorded_start + offset
    times = [
        (start + offset, end + offset, inferred)
        for start, end, inferred in _span_times(events, recorded_start)
    ]
    run_end = max([run_start, *(end for _, end, _ in times)])

    root_attrs = {**common, **_run_attributes(trace, include_content)}
    if shift_to_now:
        root_attrs["agentreplay.time_shifted"] = True
    root = tracer.start_span(ROOT_SPAN_NAME, start_time=run_start, attributes=root_attrs)
    root_ctx = otel_trace.set_span_in_context(root)

    # Clock/RNG draws are instants: events on the root, not spans.
    for event in events:
        if isinstance(event, ClockEvent):
            root.add_event(
                "agentreplay.clock",
                attributes={
                    "agentreplay.seq": event.seq,
                    "agentreplay.recorded_time": event.recorded_time.isoformat(),
                },
                timestamp=_to_ns(event.ts) + offset,
            )
        elif isinstance(event, RandomEvent):
            root.add_event(
                "agentreplay.random",
                attributes={
                    "agentreplay.seq": event.seq,
                    "agentreplay.source": event.source,
                    "agentreplay.value": event.value,
                },
                timestamp=_to_ns(event.ts) + offset,
            )

    # Calls, grouped under one span per consecutive run of the same LangGraph
    # node (schema v2) so backends show the agent's step tree. Calls without
    # a node (v1 traces, code outside a graph) hang directly off the root.
    timed_calls = [
        (event, timing) for event, timing in zip(events, times)
        if isinstance(event, (LLMCallEvent, ToolCallEvent))
    ]
    for node, group in _group_by_node(timed_calls):
        parent_ctx = root_ctx
        node_span = None
        if node is not None:
            node_span = tracer.start_span(
                node,
                context=root_ctx,
                start_time=min(start for _, (start, _, _) in group),
                attributes={**common, "agentreplay.node": node},
            )
            parent_ctx = otel_trace.set_span_in_context(node_span)

        for event, (start, end, inferred) in group:
            timing_attrs = {"agentreplay.timing.inferred": inferred}
            if isinstance(event, LLMCallEvent):
                span = tracer.start_span(
                    f"chat {event.model_id or event.model_name or 'unknown'}",
                    context=parent_ctx,
                    kind=SpanKind.CLIENT,
                    start_time=start,
                    attributes={
                        **common, **timing_attrs,
                        **_llm_attributes(event, trace, include_content),
                    },
                )
            else:
                span = tracer.start_span(
                    f"execute_tool {event.tool_name}",
                    context=parent_ctx,
                    kind=SpanKind.INTERNAL,
                    start_time=start,
                    attributes={
                        **common, **timing_attrs,
                        **_tool_attributes(event, include_content),
                    },
                )
                if event.error:
                    error_type = event.error.split(":", 1)[0].strip()
                    span.set_attribute("error.type", error_type)
                    span.set_status(Status(
                        StatusCode.ERROR,
                        event.error if include_content else error_type,
                    ))
            span.end(end_time=end)

        if node_span is not None:
            node_span.end(end_time=max(end for _, (_, end, _) in group))

    root.end(end_time=run_end)
    return format(root.get_span_context().trace_id, "032x")


def otlp_tracer_provider(
    endpoint: str | None = None,
    headers: dict[str, str] | None = None,
    *,
    service_name: str = "agentreplay",
    exporter: "SpanExporter | None" = None,
) -> "TracerProvider":
    """Build a ``TracerProvider`` that batches spans to an OTLP/HTTP endpoint.

    Args:
        endpoint: Full traces URL, e.g. ``http://localhost:4318/v1/traces``.
            ``None`` defers to the standard ``OTEL_EXPORTER_OTLP_*`` env vars.
        headers: Extra HTTP headers (auth). ``None`` defers to
            ``OTEL_EXPORTER_OTLP_HEADERS``.
        service_name: ``service.name`` resource attribute.
        exporter: Use this exporter instead of building an OTLP one
            (console output, tests).
    """
    _require_otel()
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    if exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


def langfuse_otlp_config(
    env: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    """Return ``(endpoint, headers)`` for Langfuse's OTLP ingestion API.

    Reads the same env vars as the Langfuse SDK: ``LANGFUSE_PUBLIC_KEY``,
    ``LANGFUSE_SECRET_KEY`` and ``LANGFUSE_BASE_URL`` / ``LANGFUSE_HOST``
    (default: Langfuse Cloud EU). Auth is HTTP Basic ``public:secret``.

    ``x-langfuse-ingestion-version: 4`` opts into real-time ingestion; without
    it, data from plain OTel exporters can take up to 15 minutes to appear.

    Raises:
        ValueError: if either key is missing.
    """
    env = os.environ if env is None else env
    public_key = env.get("LANGFUSE_PUBLIC_KEY")
    secret_key = env.get("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        raise ValueError(
            "Langfuse export needs LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY "
            "set in the environment."
        )
    host = (
        env.get("LANGFUSE_BASE_URL") or env.get("LANGFUSE_HOST") or LANGFUSE_DEFAULT_HOST
    ).rstrip("/")
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    return f"{host}/api/public/otel/v1/traces", {
        "Authorization": f"Basic {token}",
        "x-langfuse-ingestion-version": "4",
    }


class ResultTrackingExporter:
    """Wraps a ``SpanExporter`` and remembers whether any export failed.

    OTel exporters log failures instead of raising, which would let a CI
    export step pass silently. The CLI checks ``failed`` to set its exit code.
    """

    def __init__(self, inner: "SpanExporter") -> None:
        self._inner = inner
        self.failed = False

    def export(self, spans: Sequence[Any]) -> Any:
        from opentelemetry.sdk.trace.export import SpanExportResult

        result = self._inner.export(spans)
        if result != SpanExportResult.SUCCESS:
            self.failed = True
        return result

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._inner.force_flush(timeout_millis)


# ---------------------------------------------------------------------------
# Attribute builders
# ---------------------------------------------------------------------------

def _run_attributes(trace: Trace, include_content: bool) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "agentreplay.schema_version": trace.schema_version,
        "agentreplay.event_count": len(trace.events),
        "agentreplay.recorded_at": trace.created_at.isoformat(),
    }
    for key, value in trace.metadata.items():
        # Internal keys (e.g. the stored agent input) are run content, not tags.
        if key.startswith("_agentreplay"):
            continue
        attrs[f"agentreplay.metadata.{key}"] = _attr_value(value)

    if include_content and "_agentreplay_input" in trace.metadata:
        attrs["langfuse.observation.input"] = _json(trace.metadata["_agentreplay_input"])
    return attrs


def _llm_attributes(
    event: LLMCallEvent, trace: Trace, include_content: bool,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "gen_ai.operation.name": "chat",
        "langfuse.observation.type": "generation",
        "agentreplay.event_type": "llm_call",
        "agentreplay.seq": event.seq,
        "agentreplay.hash": event.hash,
        "agentreplay.llm_type": event.model_name,
    }
    if event.node:
        attrs["agentreplay.node"] = event.node

    # v2 traces carry the provider model id (what Langfuse prices against);
    # v1 traces only have LangChain's ``_llm_type`` family ("anthropic-chat").
    model = event.model_id or event.model_name
    if model:
        attrs["gen_ai.request.model"] = model
    if event.model_id:
        attrs["gen_ai.response.model"] = event.model_id

    if event.usage is not None:
        attrs["gen_ai.usage.input_tokens"] = event.usage.input_tokens
        attrs["gen_ai.usage.output_tokens"] = event.usage.output_tokens
        # Cache counts are a subset of input_tokens. Kept outside gen_ai.usage.*
        # because Langfuse sums every key under that prefix into the total,
        # which would double-count cached tokens.
        if event.usage.cache_read_tokens is not None:
            attrs["agentreplay.usage.cache_read_tokens"] = event.usage.cache_read_tokens
        if event.usage.cache_creation_tokens is not None:
            attrs["agentreplay.usage.cache_creation_tokens"] = event.usage.cache_creation_tokens

    if include_content:
        output = _resolve_output(event, trace)
        # GenAI semconv shape, for generic OTel backends.
        attrs["gen_ai.input.messages"] = _json([
            {
                "role": _ROLE_MAP.get(m.type, m.type),
                "parts": [{"type": "text", "content": m.content}],
            }
            for m in event.input_messages
        ])
        attrs["gen_ai.output.messages"] = _json([
            {"role": "assistant", "parts": [{"type": "text", "content": output}]},
        ])
        # Langfuse renders [{role, content}] as a chat transcript.
        attrs["langfuse.observation.input"] = _json([
            {"role": _ROLE_MAP.get(m.type, m.type), "content": m.content}
            for m in event.input_messages
        ])
        attrs["langfuse.observation.output"] = output
        if event.kwargs:
            attrs["agentreplay.llm.kwargs"] = _json(event.kwargs)
    return attrs


def _tool_attributes(event: ToolCallEvent, include_content: bool) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": event.tool_name,
        "langfuse.observation.type": "tool",
        "agentreplay.event_type": "tool_call",
        "agentreplay.seq": event.seq,
        "agentreplay.hash": event.hash,
    }
    if event.node:
        attrs["agentreplay.node"] = event.node
    if include_content:
        # Langfuse falls back to these for observation input/output.
        attrs["gen_ai.tool.call.arguments"] = _json(event.input_args)
        attrs["gen_ai.tool.call.result"] = event.output
    return attrs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_otel():
    """Import ``opentelemetry.trace`` or fail with an install hint."""
    try:
        from opentelemetry import trace as otel_trace
    except ImportError as exc:
        raise ImportError(INSTALL_HINT) from exc
    return otel_trace


def _span_times(events: list[Any], run_start: int) -> list[tuple[int, int, bool]]:
    """``(start_ns, end_ns, inferred)`` for each event, aligned with *events*.

    Schema v2 events carry a measured ``start_ts`` + ``duration_ms``. v1
    events only have ``ts`` (completion), so their start is inferred as the
    latest completion seen before them — never after their own end.
    """
    times: list[tuple[int, int, bool]] = []
    cursor = run_start
    for event in events:
        completed = _to_ns(event.ts)
        start_ts = getattr(event, "start_ts", None)
        duration_ms = getattr(event, "duration_ms", None)
        if start_ts is not None and duration_ms is not None:
            start = _to_ns(start_ts)
            times.append((start, start + int(duration_ms * 1_000_000), False))
        else:
            times.append((min(cursor, completed), completed, True))
        cursor = max(cursor, completed)
    return times


def _group_by_node(
    timed_calls: list[tuple[Any, tuple[int, int, bool]]],
) -> list[tuple[str | None, list[tuple[Any, tuple[int, int, bool]]]]]:
    """Split calls into consecutive runs sharing the same ``node``.

    A node that runs twice (agent loop) yields two groups, matching how the
    graph actually executed. Parallel nodes interleave by ``seq`` and so may
    split into several short groups — fragmented, but never mis-attributed.
    """
    groups: list[tuple[str | None, list[tuple[Any, tuple[int, int, bool]]]]] = []
    for item in timed_calls:
        node = getattr(item[0], "node", None)
        if groups and groups[-1][0] == node:
            groups[-1][1].append(item)
        else:
            groups.append((node, [item]))
    return groups


def _resolve_output(event: LLMCallEvent, trace: Trace) -> str:
    """Prefer the content-addressed blob when the output was stored there."""
    if event.output_blob_key and event.output_blob_key in trace.blobs:
        return trace.blobs[event.output_blob_key]
    return event.output


def _to_ns(dt: datetime) -> int:
    """Exact epoch nanoseconds (float ``timestamp()`` loses sub-µs precision).

    Naive datetimes are treated as UTC — the recorder always writes UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = dt - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def _attr_value(value: Any) -> Any:
    """OTel attributes accept only scalars (and homogeneous sequences)."""
    if isinstance(value, (str, bool, int, float)):
        return value
    return _json(value)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _package_version() -> str:
    try:
        from importlib.metadata import version
        return version("agentreplay")
    except Exception:
        return "0.0.0"

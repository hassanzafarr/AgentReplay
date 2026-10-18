"""Tests for agentreplay.integrations.otel — OpenTelemetry export.

Proves: a trace becomes a root span with one child per LLM/tool event;
clock/RNG draws become span events, not spans; GenAI + Langfuse attributes
are set; content (prompts, outputs, tool I/O, error messages) is withheld
unless opted in; inferred timing never produces negative spans; Langfuse
OTLP config is built from env; the CLI exports to console and fails loudly
on bad input or a failing backend.

Does NOT cover: delivery to a real OTLP collector or Langfuse instance
(network), the OTLP wire format itself (owned by the OTel SDK), or the
global tracer provider default.
"""

from __future__ import annotations

import base64
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExportResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from agentreplay import cli
from agentreplay.integrations.otel import (
    ROOT_SPAN_NAME,
    ResultTrackingExporter,
    export_trace,
    langfuse_otlp_config,
)
from agentreplay.recorder.trace_writer import TraceWriter
from agentreplay.schema.trace import (
    ClockEvent,
    LLMCallEvent,
    MessageRecord,
    RandomEvent,
    TokenUsage,
    ToolCallEvent,
    Trace,
)

T0 =datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
SECRETS = (
    "SECRET-PROMPT", "SECRET-COMPLETION", "SECRET-ARGS",
    "SECRET-RESULT", "SECRET-ERROR", "SECRET-INPUT",
)


def _at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _ns(seconds: float) -> int:
    return int(T0.timestamp()) * 1_000_000_000 + int(seconds * 1_000_000_000)


@pytest.fixture
def otel():
    """Tracer provider that keeps finished spans in memory."""
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    return provider, memory


@pytest.fixture
def sample_trace() -> Trace:
    """Clock → LLM → tool → RNG → failing tool, with fixed timestamps."""
    trace = Trace(
        created_at=T0,
        metadata={
            "agent": "demo",
            "tags": ["a", "b"],
            "_agentreplay_input": {"topic": "SECRET-INPUT"},
        },
    )
    trace.add_event(ClockEvent(seq=0, ts=_at(0.1), recorded_time=T0))
    trace.add_event(LLMCallEvent(
        seq=1,
        ts=_at(1.0),
        hash="h-llm",
        model_name="standin",
        input_messages=[
            MessageRecord(type="system", content="be terse"),
            MessageRecord(type="human", content="SECRET-PROMPT"),
        ],
        output="SECRET-COMPLETION",
    ))
    trace.add_event(ToolCallEvent(
        seq=2,
        ts=_at(1.5),
        hash="h-tool",
        tool_name="search",
        input_args={"q": "SECRET-ARGS"},
        output="SECRET-RESULT",
    ))
    trace.add_event(RandomEvent(seq=3, ts=_at(1.6), source="uuid4", value="abc"))
    trace.add_event(ToolCallEvent(
        seq=4,
        ts=_at(2.0),
        hash="h-fail",
        tool_name="fail_tool",
        input_args={},
        error="ValueError: SECRET-ERROR",
    ))
    return trace


def _spans(memory):
    spans = memory.get_finished_spans()
    by_name = {s.name: s for s in spans}
    return spans, by_name


def _all_attribute_text(spans) -> str:
    """Every attribute value, event attribute and status text, concatenated."""
    parts = []
    for s in spans:
        parts.extend(str(v) for v in (s.attributes or {}).values())
        parts.append(str(s.status.description or ""))
        for e in s.events:
            parts.extend(str(v) for v in (e.attributes or {}).values())
    return " ".join(parts)


class TestSpanTree:
    def test_root_plus_one_child_per_llm_and_tool_event(self, otel, sample_trace):
        """3 call events → 3 child spans, all parented to the single root.

        Does not cover: parallel nodes (all children are siblings by design).
        """
        provider, memory = otel
        export_trace(sample_trace, tracer_provider=provider)
        spans, by_name = _spans(memory)

        assert sorted(by_name) == sorted([
            ROOT_SPAN_NAME, "chat standin",
            "execute_tool search", "execute_tool fail_tool",
        ])
        root = by_name[ROOT_SPAN_NAME]
        assert root.parent is None
        for s in spans:
            assert s.context.trace_id == root.context.trace_id
            if s is not root:
                assert s.parent.span_id == root.context.span_id

    def test_returns_hex_trace_id_of_exported_spans(self, otel, sample_trace):
        """The returned id lets callers link to the trace in their backend."""
        provider, memory = otel
        trace_id = export_trace(sample_trace, tracer_provider=provider)
        root = _spans(memory)[1][ROOT_SPAN_NAME]

        assert trace_id == format(root.context.trace_id, "032x")
        assert len(trace_id) == 32

    def test_clock_and_random_become_root_span_events(self, otel, sample_trace):
        """Instant draws are events on the root, never standalone spans."""
        provider, memory = otel
        export_trace(sample_trace, tracer_provider=provider)
        root = _spans(memory)[1][ROOT_SPAN_NAME]

        names = [e.name for e in root.events]
        assert names == ["agentreplay.clock", "agentreplay.random"]
        assert root.events[1].attributes["agentreplay.value"] == "abc"
        assert root.events[0].timestamp == _ns(0.1)

    def test_empty_trace_exports_root_only(self, otel):
        """A run with no intercepted calls still shows up as one span."""
        provider, memory = otel
        export_trace(Trace(created_at=T0), tracer_provider=provider)
        spans, _ = _spans(memory)

        assert [s.name for s in spans] == [ROOT_SPAN_NAME]
        assert spans[0].start_time == spans[0].end_time == _ns(0)


class TestAttributes:
    def test_llm_span_has_genai_and_langfuse_attributes(self, otel, sample_trace):
        """Langfuse needs observation type + model to render a generation."""
        provider, memory = otel
        export_trace(sample_trace, tracer_provider=provider)
        attrs = _spans(memory)[1]["chat standin"].attributes

        assert attrs["gen_ai.operation.name"] == "chat"
        assert attrs["gen_ai.request.model"] == "standin"
        assert attrs["langfuse.observation.type"] == "generation"
        assert attrs["agentreplay.seq"] == 1
        assert attrs["agentreplay.hash"] == "h-llm"
        assert attrs["agentreplay.run_id"] == sample_trace.run_id

    def test_tool_span_attributes(self, otel, sample_trace):
        provider, memory = otel
        export_trace(sample_trace, tracer_provider=provider)
        attrs = _spans(memory)[1]["execute_tool search"].attributes

        assert attrs["gen_ai.operation.name"] == "execute_tool"
        assert attrs["gen_ai.tool.name"] == "search"
        assert attrs["langfuse.observation.type"] == "tool"

    def test_tool_error_sets_error_status(self, otel, sample_trace):
        """Failed tools are ERROR spans; message withheld without opt-in."""
        provider, memory = otel
        export_trace(sample_trace, tracer_provider=provider)
        span = _spans(memory)[1]["execute_tool fail_tool"]

        assert span.status.status_code == StatusCode.ERROR
        assert span.status.description == "ValueError"
        assert span.attributes["error.type"] == "ValueError"

    def test_metadata_exported_internal_keys_skipped(self, otel, sample_trace):
        """User metadata becomes root attributes; the stored agent input
        (an internal key holding run content) does not."""
        provider, memory = otel
        export_trace(sample_trace, tracer_provider=provider)
        attrs = _spans(memory)[1][ROOT_SPAN_NAME].attributes

        assert attrs["agentreplay.metadata.agent"] == "demo"
        assert json.loads(attrs["agentreplay.metadata.tags"]) == ["a", "b"]
        assert not any("_agentreplay" in k for k in attrs)
        assert attrs["agentreplay.event_count"] == 5

    def test_environment_set_on_every_span(self, otel, sample_trace):
        """Langfuse filters per span, so the tag must be on all of them."""
        provider, memory = otel
        export_trace(sample_trace, tracer_provider=provider, environment="replay")
        spans, _ = _spans(memory)

        assert all(
            s.attributes["deployment.environment.name"] == "replay" for s in spans
        )


class TestContentPrivacy:
    def test_content_withheld_by_default(self, otel, sample_trace):
        """No prompt, completion, tool I/O, error text or input leaks."""
        provider, memory = otel
        export_trace(sample_trace, tracer_provider=provider)
        text = _all_attribute_text(_spans(memory)[0])

        for secret in SECRETS:
            assert secret not in text

    def test_content_exported_when_opted_in(self, otel, sample_trace):
        """Opt-in fills both GenAI semconv and Langfuse input/output fields."""
        provider, memory = otel
        export_trace(sample_trace, tracer_provider=provider, include_content=True)
        _, by_name = _spans(memory)

        llm = by_name["chat standin"].attributes
        semconv_in = json.loads(llm["gen_ai.input.messages"])
        assert semconv_in[1] == {
            "role": "user",
            "parts": [{"type": "text", "content": "SECRET-PROMPT"}],
        }
        assert json.loads(llm["langfuse.observation.input"])[0] == {
            "role": "system", "content": "be terse",
        }
        assert llm["langfuse.observation.output"] == "SECRET-COMPLETION"

        tool = by_name["execute_tool search"].attributes
        assert json.loads(tool["gen_ai.tool.call.arguments"]) == {"q": "SECRET-ARGS"}
        assert tool["gen_ai.tool.call.result"] == "SECRET-RESULT"

        fail = by_name["execute_tool fail_tool"]
        assert fail.status.description == "ValueError: SECRET-ERROR"

        root = by_name[ROOT_SPAN_NAME].attributes
        assert json.loads(root["langfuse.observation.input"]) == {"topic": "SECRET-INPUT"}

    def test_blob_stored_output_is_resolved(self, otel):
        """Large outputs live in trace.blobs; export must send the real text."""
        provider, memory = otel
        trace = Trace(created_at=T0, blobs={"k1": "FULL-BLOB-OUTPUT"})
        trace.add_event(LLMCallEvent(
            seq=0, ts=_at(1), model_name="m", output="<blob>", output_blob_key="k1",
        ))
        export_trace(trace, tracer_provider=provider, include_content=True)
        attrs = _spans(memory)[1]["chat m"].attributes

        assert attrs["langfuse.observation.output"] == "FULL-BLOB-OUTPUT"


class TestInferredTiming:
    def test_span_starts_at_previous_event_completion(self, otel, sample_trace):
        """Start = previous event's ts (clock/RNG included), end = own ts.

        Does not cover: real latency — schema v1 has no start timestamps.
        """
        provider, memory = otel
        export_trace(sample_trace, tracer_provider=provider)
        _, by_name = _spans(memory)

        expected = {
            ROOT_SPAN_NAME: (0.0, 2.0),
            "chat standin": (0.1, 1.0),
            "execute_tool search": (1.0, 1.5),
            "execute_tool fail_tool": (1.6, 2.0),
        }
        for name, (start, end) in expected.items():
            assert (by_name[name].start_time, by_name[name].end_time) == (_ns(start), _ns(end)), name
        assert by_name["chat standin"].attributes["agentreplay.timing.inferred"] is True

    def test_out_of_order_timestamps_never_negative(self, otel):
        """Parallel nodes can complete out of seq order; spans stay valid."""
        provider, memory = otel
        trace = Trace(created_at=T0)
        trace.add_event(ToolCallEvent(seq=0, ts=_at(3), tool_name="slow"))
        trace.add_event(ToolCallEvent(seq=1, ts=_at(2), tool_name="fast"))
        export_trace(trace, tracer_provider=provider)

        for span in _spans(memory)[0]:
            assert span.start_time <= span.end_time


@pytest.fixture
def v2_trace() -> Trace:
    """answer → lookup → answer (agent loop), with measured timing + usage."""
    trace = Trace(created_at=T0)
    trace.add_event(LLMCallEvent(
        seq=0, ts=_at(1.2), hash="a", model_name="anthropic-chat",
        start_ts=_at(0.2), duration_ms=1000.0, node="answer", model_id="claude-x",
        usage=TokenUsage(
            input_tokens=100, output_tokens=20, total_tokens=120, cache_read_tokens=80,
        ),
    ))
    trace.add_event(ToolCallEvent(
        seq=1, ts=_at(1.6), hash="t", tool_name="lookup_order",
        start_ts=_at(1.3), duration_ms=250.0, node="lookup",
    ))
    trace.add_event(LLMCallEvent(
        seq=2, ts=_at(2.5), hash="b", model_name="anthropic-chat",
        start_ts=_at(1.7), duration_ms=800.0, node="answer", model_id="claude-x",
    ))
    return trace


class TestSchemaV2Export:
    def test_measured_timing_used(self, otel, v2_trace):
        """start_ts + duration_ms win over inference; flagged as measured."""
        provider, memory = otel
        export_trace(v2_trace, tracer_provider=provider)
        tool = _spans(memory)[1]["execute_tool lookup_order"]

        assert (tool.start_time, tool.end_time) == (_ns(1.3), _ns(1.55))
        assert tool.attributes["agentreplay.timing.inferred"] is False

    def test_calls_grouped_under_node_spans(self, otel, v2_trace):
        """Each consecutive run of a node becomes one span; a node that
        runs twice (agent loop) appears twice, in execution order."""
        provider, memory = otel
        export_trace(v2_trace, tracer_provider=provider)
        spans = memory.get_finished_spans()
        root = next(s for s in spans if s.name == ROOT_SPAN_NAME)
        node_spans = sorted(
            (s for s in spans if s.parent and s.parent.span_id == root.context.span_id),
            key=lambda s: s.start_time,
        )

        assert [s.name for s in node_spans] == ["answer", "lookup", "answer"]
        first_answer = node_spans[0]
        assert (first_answer.start_time, first_answer.end_time) == (_ns(0.2), _ns(1.2))
        children = [s for s in spans if s.parent and s.parent.span_id == first_answer.context.span_id]
        assert [c.name for c in children] == ["chat claude-x"]
        assert children[0].attributes["agentreplay.node"] == "answer"

    def test_model_id_and_usage_attributes(self, otel, v2_trace):
        """Langfuse prices by gen_ai.request.model + gen_ai.usage.*; cache
        counts stay outside gen_ai.usage.* so they aren't summed twice."""
        provider, memory = otel
        export_trace(v2_trace, tracer_provider=provider)
        chat = next(
            s for s in memory.get_finished_spans()
            if s.name == "chat claude-x" and s.attributes["agentreplay.seq"] == 0
        )
        attrs = chat.attributes

        assert attrs["gen_ai.request.model"] == "claude-x"
        assert attrs["gen_ai.response.model"] == "claude-x"
        assert attrs["agentreplay.llm_type"] == "anthropic-chat"
        assert attrs["gen_ai.usage.input_tokens"] == 100
        assert attrs["gen_ai.usage.output_tokens"] == 20
        assert attrs["agentreplay.usage.cache_read_tokens"] == 80
        assert not any(k.startswith("gen_ai.usage.cache") for k in attrs)

    def test_llm_without_usage_has_no_usage_attributes(self, otel, v2_trace):
        """Replay events have no usage; exporting must not invent zeros."""
        provider, memory = otel
        export_trace(v2_trace, tracer_provider=provider)
        chat = next(
            s for s in memory.get_finished_spans()
            if s.name == "chat claude-x" and s.attributes["agentreplay.seq"] == 2
        )

        assert not any(k.startswith("gen_ai.usage") for k in chat.attributes)

    def test_v1_trace_stays_flat(self, otel, sample_trace):
        """No node info → calls hang off the root, no node spans invented."""
        provider, memory = otel
        export_trace(sample_trace, tracer_provider=provider)
        spans = memory.get_finished_spans()
        root = next(s for s in spans if s.name == ROOT_SPAN_NAME)

        assert len(spans) == 4
        assert all(s.parent.span_id == root.context.span_id for s in spans if s is not root)


class TestShiftToNow:
    def test_run_moves_to_now_preserving_relative_timing(self, otel, v2_trace):
        """Old traces get re-timed to 'now' (retention windows) but every
        offset and duration inside the run is unchanged."""
        import time

        provider, memory = otel
        before = time.time_ns()
        export_trace(v2_trace, tracer_provider=provider, shift_to_now=True)
        after = time.time_ns()
        _, by_name = _spans(memory)
        root, tool = by_name[ROOT_SPAN_NAME], by_name["execute_tool lookup_order"]

        assert before <= root.start_time <= after
        assert tool.start_time - root.start_time == _ns(1.3) - _ns(0)
        assert tool.end_time - tool.start_time == _ns(0.25) - _ns(0)
        assert root.attributes["agentreplay.time_shifted"] is True
        assert root.attributes["agentreplay.recorded_at"] == T0.isoformat()

    def test_default_keeps_recorded_time(self, otel, v2_trace):
        provider, memory = otel
        export_trace(v2_trace, tracer_provider=provider)
        root = _spans(memory)[1][ROOT_SPAN_NAME]

        assert root.start_time == _ns(0)
        assert "agentreplay.time_shifted" not in root.attributes


class TestLangfuseConfig:
    def test_builds_endpoint_and_basic_auth(self):
        endpoint, headers = langfuse_otlp_config({
            "LANGFUSE_PUBLIC_KEY": "pk-lf-1",
            "LANGFUSE_SECRET_KEY": "sk-lf-2",
            "LANGFUSE_HOST": "https://us.cloud.langfuse.com/",
        })

        assert endpoint == "https://us.cloud.langfuse.com/api/public/otel/v1/traces"
        scheme, token = headers["Authorization"].split(" ")
        assert scheme == "Basic"
        assert base64.b64decode(token).decode() == "pk-lf-1:sk-lf-2"
        # Real-time ingestion; without it Langfuse may delay OTel data ~15 min.
        assert headers["x-langfuse-ingestion-version"] == "4"

    def test_defaults_to_cloud_and_prefers_base_url(self):
        endpoint, _ = langfuse_otlp_config({
            "LANGFUSE_PUBLIC_KEY": "p", "LANGFUSE_SECRET_KEY": "s",
        })
        assert endpoint == "https://cloud.langfuse.com/api/public/otel/v1/traces"

        endpoint, _ = langfuse_otlp_config({
            "LANGFUSE_PUBLIC_KEY": "p", "LANGFUSE_SECRET_KEY": "s",
            "LANGFUSE_BASE_URL": "http://localhost:3000",
            "LANGFUSE_HOST": "https://ignored.example",
        })
        assert endpoint == "http://localhost:3000/api/public/otel/v1/traces"

    def test_missing_keys_raise(self):
        with pytest.raises(ValueError, match="LANGFUSE_PUBLIC_KEY"):
            langfuse_otlp_config({"LANGFUSE_SECRET_KEY": "s"})


class TestOptionalDependency:
    def test_missing_otel_gives_install_hint(self, monkeypatch, sample_trace):
        """Core package must not need OTel; using export without it says how
        to install it instead of a bare ModuleNotFoundError."""
        monkeypatch.setitem(sys.modules, "opentelemetry", None)
        with pytest.raises(ImportError, match=r"agentreplay\[otel\]"):
            export_trace(sample_trace)


class TestResultTrackingExporter:
    def test_records_failure(self):
        """OTel exporters log failures instead of raising; we must notice."""
        class Failing:
            def export(self, spans):
                return SpanExportResult.FAILURE

        tracker = ResultTrackingExporter(Failing())
        assert tracker.export([]) == SpanExportResult.FAILURE
        assert tracker.failed is True

    def test_success_leaves_flag_clear(self):
        tracker = ResultTrackingExporter(InMemorySpanExporter())
        tracker.export([])
        assert tracker.failed is False


class TestGoldenTraces:
    def test_example_traces_export(self, otel):
        """Real recorded traces from the demo agent export without error and
        produce one span per LLM/tool event plus the root."""
        provider, memory = otel
        trace_dir = Path(__file__).parent.parent / "examples" / "research_agent" / "traces"
        paths = sorted(trace_dir.glob("*.trace.json"))
        if not paths:
            pytest.skip("no example traces present")

        for path in paths:
            memory.clear()
            trace = TraceWriter.read(path)
            export_trace(trace, tracer_provider=provider, include_content=True)
            calls = [e for e in trace.events if e.event_type.value in ("llm_call", "tool_call")]
            call_spans = [
                s for s in memory.get_finished_spans()
                if "agentreplay.event_type" in (s.attributes or {})
            ]
            assert len(call_spans) == len(calls)


class TestCLI:
    def _run(self, monkeypatch, *argv: str) -> int:
        monkeypatch.setattr(sys, "argv", ["agentreplay", *argv])
        return cli.main()

    def test_export_directory_to_console(self, monkeypatch, capsys, tmp_path, sample_trace):
        """Directory input expands to its traces; spans print as JSON to
        stdout, status lines go to stderr; content withheld by default."""
        TraceWriter(tmp_path).write(sample_trace)

        rc = self._run(monkeypatch, "export", str(tmp_path), "--console")
        out, err = capsys.readouterr()

        assert rc == 0
        assert '"name": "chat standin"' in out
        assert "SECRET-PROMPT" not in out
        assert "1 trace(s) sent to console" in err

    def test_old_trace_warns_unless_shifted(self, monkeypatch, capsys, tmp_path, sample_trace):
        """Retention drops are silent server-side, so the CLI must say so."""
        path = TraceWriter(tmp_path).write(sample_trace)  # recorded 2026-01-01

        assert self._run(monkeypatch, "export", str(path), "--console") == 0
        assert "--shift-to-now" in capsys.readouterr().err

        assert self._run(monkeypatch, "export", str(path), "--console", "--shift-to-now") == 0
        assert "warning" not in capsys.readouterr().err

    def test_missing_file_fails(self, monkeypatch, capsys, tmp_path):
        rc = self._run(monkeypatch, "export", str(tmp_path / "nope.trace.json"), "--console")
        assert rc == 1
        assert "not found" in capsys.readouterr().err

    def test_bad_header_fails(self, monkeypatch, capsys, tmp_path, sample_trace):
        path = TraceWriter(tmp_path).write(sample_trace)
        rc = self._run(monkeypatch, "export", str(path), "--header", "no-equals")
        assert rc == 1
        assert "KEY=VALUE" in capsys.readouterr().err

    def test_langfuse_without_keys_fails(self, monkeypatch, capsys, tmp_path, sample_trace):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        path = TraceWriter(tmp_path).write(sample_trace)

        rc = self._run(monkeypatch, "export", str(path), "--langfuse")
        assert rc == 1
        assert "LANGFUSE_PUBLIC_KEY" in capsys.readouterr().err

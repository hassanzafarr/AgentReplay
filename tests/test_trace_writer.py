"""Tests for agentreplay.recorder.trace_writer — JSON serialization.

Proves: traces write to valid JSON, round-trip through Pydantic, file
paths are correct.

Does NOT cover: concurrent writes, file system errors, large traces.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentreplay.recorder.trace_writer import TraceWriter
from agentreplay.schema.trace import (
    LLMCallEvent,
    MessageRecord,
    ToolCallEvent,
    Trace,
)


@pytest.fixture
def trace_dir(tmp_path):
    """Temporary directory for trace files."""
    return tmp_path / "traces"


@pytest.fixture
def sample_trace():
    """A trace with mixed events for testing."""
    trace = Trace(metadata={"agent": "test", "model": "standin"})
    trace.add_event(LLMCallEvent(
        seq=0,
        hash="hash1",
        model_name="standin",
        input_messages=[MessageRecord(type="human", content="hello")],
        output="world",
    ))
    trace.add_event(ToolCallEvent(
        seq=1,
        hash="hash2",
        tool_name="search",
        input_args={"query": "test"},
        output="found it",
    ))
    return trace


class TestTraceWriter:
    def test_writes_json_file(self, trace_dir, sample_trace):
        """Write creates a JSON file at the expected path."""
        writer = TraceWriter(trace_dir)
        path = writer.write(sample_trace)

        assert path.exists()
        assert path.suffix == ".json"
        assert path.parent == trace_dir

    def test_creates_directory(self, trace_dir, sample_trace):
        """Write creates the trace directory if it doesn't exist."""
        assert not trace_dir.exists()
        writer = TraceWriter(trace_dir)
        writer.write(sample_trace)
        assert trace_dir.exists()

    def test_filename_contains_run_id(self, trace_dir, sample_trace):
        """Filename is <run_id>.trace.json."""
        writer = TraceWriter(trace_dir)
        path = writer.write(sample_trace)
        assert sample_trace.run_id in path.name

    def test_valid_json(self, trace_dir, sample_trace):
        """Written file is valid JSON."""
        writer = TraceWriter(trace_dir)
        path = writer.write(sample_trace)

        with open(path) as f:
            data = json.load(f)

        assert data["schema_version"] == 1
        assert len(data["events"]) == 2

    def test_roundtrip_through_pydantic(self, trace_dir, sample_trace):
        """Written JSON validates back through Pydantic."""
        writer = TraceWriter(trace_dir)
        path = writer.write(sample_trace)

        restored = TraceWriter.read(path)
        assert restored.schema_version == sample_trace.schema_version
        assert restored.run_id == sample_trace.run_id
        assert len(restored.events) == len(sample_trace.events)

    def test_pretty_print_default(self, trace_dir, sample_trace):
        """Default mode writes indented (human-readable) JSON."""
        writer = TraceWriter(trace_dir)
        path = writer.write(sample_trace)

        text = path.read_text()
        assert "\n" in text  # Indented output has newlines.

    def test_compact_mode(self, trace_dir, sample_trace):
        """Compact mode writes minified JSON."""
        writer = TraceWriter(trace_dir)
        path = writer.write(sample_trace, compact=True)

        text = path.read_text()
        # Compact JSON is a single line (or very few lines).
        assert text.count("\n") <= 1

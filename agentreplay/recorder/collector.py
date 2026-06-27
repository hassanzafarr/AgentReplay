"""Thread-safe event collector shared across all interception points.

Every interceptor (LLM, tool, clock, RNG) appends events to the same
``TraceCollector``. It owns the atomic ``seq`` counter so events from
concurrent nodes get a globally unique ordering index, which is how we
handle the async/parallel-nodes hard-part (plan §7.2, §7.3).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from agentreplay.schema.trace import (
    BLOB_THRESHOLD,
    Trace,
    TraceEvent,
    content_hash,
)


class TraceCollector:
    """Accumulates trace events during a recording session.

    Thread-safe: the ``seq`` counter and ``events`` list are guarded by a
    lock so parallel LangGraph nodes don't corrupt ordering.
    """

    def __init__(self, metadata: dict | None = None) -> None:
        self._trace = Trace(metadata=metadata or {})
        self._lock = threading.Lock()
        self._seq = 0

    @property
    def trace(self) -> Trace:
        return self._trace

    def next_seq(self) -> int:
        """Return the next global sequence number (atomic)."""
        with self._lock:
            seq = self._seq
            self._seq += 1
            return seq

    def add_event(self, event: TraceEvent) -> None:
        """Append an event to the trace. Assigns ``ts`` if not set."""
        with self._lock:
            self._trace.add_event(event)

    def store_blob(self, data: str) -> str | None:
        """Content-address *data* into ``blobs`` if it exceeds the threshold.

        Returns the blob key if stored, or ``None`` if the data is small
        enough to stay inline in the event.
        """
        if len(data.encode("utf-8")) <= BLOB_THRESHOLD:
            return None
        key = content_hash(data)
        with self._lock:
            self._trace.blobs[key] = data
        return key

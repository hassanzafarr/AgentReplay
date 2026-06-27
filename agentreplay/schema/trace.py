"""Pydantic models for AgentReplay trace files.

This is the contract between the recorder and replayer. Every other module
depends on these types. The schema is versioned from day one; bumping
``schema_version`` is a breaking change (Decision D3).

Design choices:
- Discriminated union on ``event_type`` keeps the event list heterogeneous but
  type-safe and lets JSON round-trip cleanly.
- Each event carries a global ``seq`` index so async/parallel node execution
  can be ordered deterministically on replay (handles the "nested/parallel
  nodes" hard-part from plan §7.3).
- Large payloads (prompts, responses) are content-addressed into ``blobs{}``
  to fight trace bloat (plan §7.5). The event stores a blob reference key;
  the blob itself lives in ``Trace.blobs``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Union
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION: int = 1
"""Frozen at 1. Any change to event shapes is a breaking schema change."""

BLOB_THRESHOLD: int = 4096
"""Payloads larger than this (bytes, UTF-8) are stored in Trace.blobs."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def content_hash(data: Any) -> str:
    """SHA-256 hex digest of the canonical JSON encoding of *data*.

    Used for two purposes:
    1. Matching replayed calls to recorded responses (Decision D2).
    2. Content-addressing large blobs in ``Trace.blobs``.
    """
    blob = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    """Discriminator for the four kinds of impure input we intercept."""

    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    CLOCK = "clock"
    RANDOM = "random"


class MessageRecord(BaseModel):
    """Minimal representation of a LangChain message for trace storage.

    We record type + content only; volatile metadata (IDs, timestamps) is
    stripped so that identical logical prompts hash identically across runs.
    """

    type: str
    content: str


class LLMCallEvent(BaseModel):
    """A single LLM invocation (prompt in, completion out)."""

    event_type: Literal[EventType.LLM_CALL] = EventType.LLM_CALL
    seq: int = Field(..., description="Global ordering index (0-based)")
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    hash: str = Field("", description="Content hash of input messages")
    model_name: str = Field("", description="LLM type identifier")
    input_messages: list[MessageRecord] = Field(default_factory=list)
    output: str = ""
    kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra kwargs passed to the model (temperature, etc.)",
    )
    # Blob references: if input or output was large, the actual content lives
    # in Trace.blobs under these keys; the inline field is set to a placeholder.
    input_blob_key: str | None = None
    output_blob_key: str | None = None


class ToolCallEvent(BaseModel):
    """A single tool invocation (args in, result out)."""

    event_type: Literal[EventType.TOOL_CALL] = EventType.TOOL_CALL
    seq: int = Field(..., description="Global ordering index (0-based)")
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    hash: str = Field("", description="Content hash of tool name + input args")
    tool_name: str = ""
    input_args: dict[str, Any] = Field(default_factory=dict)
    output: str = ""
    error: str | None = None


class ClockEvent(BaseModel):
    """A recorded datetime.now() call."""

    event_type: Literal[EventType.CLOCK] = EventType.CLOCK
    seq: int = Field(..., description="Global ordering index (0-based)")
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    hash: str = ""
    recorded_time: datetime


class RandomEvent(BaseModel):
    """A recorded random/uuid call."""

    event_type: Literal[EventType.RANDOM] = EventType.RANDOM
    seq: int = Field(..., description="Global ordering index (0-based)")
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    hash: str = ""
    source: str = Field(
        ...,
        description="Which function produced this: 'random', 'randint', 'uuid4', etc.",
    )
    value: str = Field(
        ...,
        description="String representation of the recorded value",
    )


# Discriminated union of all event types.
TraceEvent = Annotated[
    Union[LLMCallEvent, ToolCallEvent, ClockEvent, RandomEvent],
    Field(discriminator="event_type"),
]


# ---------------------------------------------------------------------------
# Top-level trace
# ---------------------------------------------------------------------------

class Trace(BaseModel):
    """A complete recorded run of a LangGraph agent.

    One JSON file per run. The ``events`` list is ordered by ``seq`` and
    contains every intercepted impure input. ``blobs`` holds large payloads
    content-addressed by SHA-256; events reference them by key.
    """

    schema_version: int = SCHEMA_VERSION
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary run metadata: agent name, model, tags, etc.",
    )
    events: list[TraceEvent] = Field(default_factory=list)
    blobs: dict[str, str] = Field(
        default_factory=dict,
        description="Content-addressed storage for large payloads",
    )

    def add_event(self, event: TraceEvent) -> None:
        """Append an event, maintaining seq ordering invariant."""
        self.events.append(event)

    def get_events_by_type(self, event_type: EventType) -> list[TraceEvent]:
        """Filter events by type. Useful for analysis and diffing."""
        return [e for e in self.events if e.event_type == event_type]

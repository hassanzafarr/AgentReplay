"""LLM call interception via a ``BaseChatModel`` wrapper.

This is the productionized version of the spike's ``RecordingChatModel``.
It sits between the LangGraph agent and the real LLM provider, intercepting
every call to capture or replay responses.

Design choice (Decision D1a): we extend ``BaseChatModel`` rather than
monkeypatching. This is the stable LangChain extension point — it works
with any provider (Anthropic, OpenAI, etc.) and survives library upgrades.

Matching strategy (Decision D2): hybrid hash → ordered cursor → miss.
- Hash the input messages to find the recorded response.
- If multiple events share a hash (e.g., retry loops), use a per-hash
  cursor to disambiguate by order.
- A miss is a *reported divergence*, not a silent fallthrough.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agentreplay.recorder.collector import TraceCollector
from agentreplay.schema.trace import (
    LLMCallEvent,
    MessageRecord,
    content_hash,
)


def _messages_to_records(messages: list[BaseMessage]) -> list[MessageRecord]:
    """Convert LangChain messages to our stable, hashable format."""
    return [MessageRecord(type=m.type, content=m.content) for m in messages]


def _hash_messages(messages: list[BaseMessage]) -> str:
    """Content hash of the input messages for matching on replay."""
    payload = [{"type": m.type, "content": m.content} for m in messages]
    return content_hash(payload)


class RecordingChatModel(BaseChatModel):
    """Intercepts LLM calls for record or replay.

    In **record mode**, delegates to the inner model and captures every
    call as an ``LLMCallEvent`` in the collector.

    In **replay mode**, serves responses from the collector's trace using
    hybrid hash+cursor matching. Never touches the inner model — proven
    by the spike's TripwireModel pattern.
    """

    inner: BaseChatModel
    mode: str = "record"  # "record" or "replay"
    collector: TraceCollector | None = None

    # Replay state: per-hash cursors for ordered fallback.
    _replay_cursors: dict[str, int] = {}

    model_config = {"arbitrary_types_allowed": True}

    @property
    def _llm_type(self) -> str:
        return f"recording({self.inner._llm_type})"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.mode == "record":
            return self._record(messages, stop, run_manager, **kwargs)
        return self._replay(messages)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Async variant — same logic, delegates to async inner in record mode."""
        if self.mode == "record":
            return await self._arecord(messages, stop, run_manager, **kwargs)
        # Replay is always sync (no I/O), but we return the same type.
        return self._replay(messages)

    # ------------------------------------------------------------------
    # Record
    # ------------------------------------------------------------------

    def _record(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None,
        run_manager: Any,
        **kwargs: Any,
    ) -> ChatResult:
        """Delegate to inner model and capture the call."""
        assert self.collector is not None, "collector required in record mode"

        result = self.inner._generate(
            messages, stop=stop, run_manager=run_manager, **kwargs,
        )
        self._capture_event(messages, result, kwargs)
        return result

    async def _arecord(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None,
        run_manager: Any,
        **kwargs: Any,
    ) -> ChatResult:
        """Async delegate to inner model and capture the call."""
        assert self.collector is not None, "collector required in record mode"

        result = await self.inner._agenerate(
            messages, stop=stop, run_manager=run_manager, **kwargs,
        )
        self._capture_event(messages, result, kwargs)
        return result

    def _capture_event(
        self,
        messages: list[BaseMessage],
        result: ChatResult,
        kwargs: dict[str, Any],
    ) -> None:
        """Build and store an LLMCallEvent from a completed call."""
        assert self.collector is not None

        msg_records = _messages_to_records(messages)
        input_hash = _hash_messages(messages)
        output_text = result.generations[0].message.content

        # Content-address large payloads.
        input_blob_key = self.collector.store_blob(
            "\n".join(m.content for m in messages)
        )
        output_blob_key = self.collector.store_blob(output_text)

        event = LLMCallEvent(
            seq=self.collector.next_seq(),
            hash=input_hash,
            model_name=self.inner._llm_type,
            input_messages=msg_records,
            output=output_text,
            kwargs={k: str(v) for k, v in kwargs.items()},  # stringify for JSON safety
            input_blob_key=input_blob_key,
            output_blob_key=output_blob_key,
        )
        self.collector.add_event(event)

    # ------------------------------------------------------------------
    # Replay
    # ------------------------------------------------------------------

    def _replay(self, messages: list[BaseMessage]) -> ChatResult:
        """Serve a recorded response. Never calls the inner model."""
        assert self.collector is not None, "collector required in replay mode"

        input_hash = _hash_messages(messages)
        event = self._lookup(input_hash)

        if event is None:
            raise LookupError(
                f"REPLAY MISS: no recorded LLM response for input hash "
                f"{input_hash[:12]}… — this is a divergence from the recorded trace."
            )

        output_text = event.output
        # If the output was blob-stored, resolve it.
        if event.output_blob_key and event.output_blob_key in self.collector.trace.blobs:
            output_text = self.collector.trace.blobs[event.output_blob_key]

        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=output_text))]
        )

    def _lookup(self, input_hash: str) -> LLMCallEvent | None:
        """Hybrid match: hash first, then per-hash cursor for repeats.

        This handles three cases:
        1. Unique hash → direct match (common case).
        2. Repeated hash (retry loops) → cursor picks the next one in order.
        3. No match → returns None (caller reports divergence).
        """
        from agentreplay.schema.trace import EventType

        candidates = [
            e for e in self.collector.trace.events
            if e.event_type == EventType.LLM_CALL and e.hash == input_hash
        ]
        if not candidates:
            return None

        cursor = self._replay_cursors.get(input_hash, 0)
        # Clamp to last candidate if cursor overshoots (defensive).
        idx = min(cursor, len(candidates) - 1)
        self._replay_cursors[input_hash] = cursor + 1
        return candidates[idx]

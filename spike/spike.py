"""Phase 0 spike: prove record/replay of LLM calls, fully offline.

The core bet (plan section 1): if we intercept every LLM call during a real
run and, on replay, hand back the recorded response in the right order, the
agent becomes perfectly reproducible at zero API cost.

This spike proves exactly that, and nothing more. It is deliberately
throwaway: the *interception design* (a BaseChatModel wrapper) survives into
Phase 1, but the in-memory trace, the ad-hoc matching, and the stand-in
model die here.

Why a stand-in model instead of a real API: no API key is available in this
environment, and more importantly a key isn't needed to prove the bet. The
interception boundary is LangChain's BaseChatModel, which is identical whether
the wrapped model is ChatAnthropic or a deterministic fake. We therefore:

  * record against a deterministic stand-in (StandInModel), and
  * replay against a TripwireModel that RAISES if it is ever called.

If replay completes successfully while wrapping a model that throws on use,
that is positive proof that zero live calls happened. This is a stronger
guarantee than a key-based run, which could only show a low bill.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def hash_messages(messages: list[BaseMessage]) -> str:
    """Stable content hash of an LLM call's input.

    Used as the matching key on replay (Decision 2). We hash the message
    type + content only; we intentionally ignore volatile metadata (ids,
    timestamps) so an identical logical prompt hashes identically across runs.
    """

    payload = [{"type": m.type, "content": m.content} for m in messages]
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class StandInModel(BaseChatModel):
    """Deterministic stand-in for a real chat model (record mode).

    Produces output purely from input so a "live" run is reproducible enough
    to be a fair test fixture. In a real deployment this is ChatAnthropic;
    the interception code below does not know or care which.
    """

    @property
    def _llm_type(self) -> str:
        return "standin"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        last = messages[-1].content
        text = f"[answer to: {last[:60]}]"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


class TripwireModel(BaseChatModel):
    """A model that must never be called (replay mode).

    If replay ever delegates to the wrapped model, this raises, failing the
    spike loudly. Surviving a full replay while wrapping this proves zero
    live LLM calls.
    """

    @property
    def _llm_type(self) -> str:
        return "tripwire"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise RuntimeError("TRIPWIRE: a live LLM call happened during replay")


class RecordingChatModel(BaseChatModel):
    """The interception layer (Decision 1a), in spike form.

    Wraps an inner BaseChatModel.

      * record mode: delegate to inner, append (hash, input, output) to `trace`.
      * replay mode: never touch inner; look up the recorded response by input
        hash, falling back to call order, and on a miss raise (the spike treats
        a miss as failure; Phase 2 will treat it as a reported divergence).
    """

    # pydantic v2 model: declare fields so assignment is allowed.
    inner: BaseChatModel
    mode: str = "record"
    trace: list = []
    _cursor: int = 0

    model_config = {"arbitrary_types_allowed": True}

    @property
    def _llm_type(self) -> str:
        return "recording"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        key = hash_messages(messages)
        if self.mode == "record":
            result = self.inner._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            out_text = result.generations[0].message.content
            self.trace.append(
                {
                    "seq": len(self.trace),
                    "hash": key,
                    "input": [{"type": m.type, "content": m.content} for m in messages],
                    "output": out_text,
                }
            )
            return result

        # replay mode: serve from trace, never call inner.
        match = self._lookup(key)
        if match is None:
            raise LookupError(f"REPLAY MISS: no recorded response for input hash {key[:12]}")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=match["output"]))])

    def _lookup(self, key: str) -> dict[str, Any] | None:
        """Hybrid match: hash first, then ordered cursor among same-hash events.

        The cursor disambiguates repeated identical prompts (retry loops) and
        gives stable behaviour when two events share a hash.
        """

        candidates = [e for e in self.trace if e["hash"] == key]
        if not candidates:
            return None
        # advance through same-hash candidates in recorded order
        idx = min(self._cursor, len(candidates) - 1)
        self._cursor += 1
        return candidates[idx]

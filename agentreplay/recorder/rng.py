"""Virtualized randomness and UUID generation for deterministic replay.

Same design as ``clock.py`` (Decision D5): context-manager scoped, not
global patching. Agent code should use ``agentreplay.random()``,
``agentreplay.randint()``, and ``agentreplay.uuid4()`` as drop-ins.

Direct calls to ``random.random()`` or ``uuid.uuid4()`` bypass
interception (documented v1 limitation).
"""

from __future__ import annotations

import contextvars
import random as _random
import uuid as _uuid

from agentreplay.recorder.collector import TraceCollector
from agentreplay.schema.trace import EventType, RandomEvent

_active_rng: contextvars.ContextVar[VirtualRNG | None] = contextvars.ContextVar(
    "_active_rng", default=None,
)


class VirtualRNG:
    """Context manager that virtualizes random/uuid within a recording session."""

    def __init__(self, collector: TraceCollector, mode: str = "record") -> None:
        self._collector = collector
        self._mode = mode
        self._cursor = 0

    def __enter__(self) -> VirtualRNG:
        self._token = _active_rng.set(self)
        return self

    def __exit__(self, *exc: object) -> None:
        _active_rng.reset(self._token)

    def _record_or_replay(self, source: str, real_fn: callable) -> str:
        """Core logic: record a real value or replay a recorded one."""
        if self._mode == "record":
            value = str(real_fn())
            event = RandomEvent(
                seq=self._collector.next_seq(),
                source=source,
                value=value,
            )
            self._collector.add_event(event)
            return value

        # Replay: find next recorded random event with matching source.
        random_events = [
            e for e in self._collector.trace.get_events_by_type(EventType.RANDOM)
            if e.source == source
        ]
        matching_events = random_events[self._cursor:]
        if not matching_events:
            raise LookupError(
                f"REPLAY MISS: no more recorded '{source}' events "
                f"(cursor={self._cursor})"
            )
        value = matching_events[0].value
        self._cursor += 1
        return value

    def random(self) -> float:
        return float(self._record_or_replay("random", _random.random))

    def randint(self, a: int, b: int) -> int:
        return int(self._record_or_replay("randint", lambda: _random.randint(a, b)))

    def uuid4(self) -> str:
        return self._record_or_replay("uuid4", _uuid.uuid4)


# ------------------------------------------------------------------
# Public drop-in API
# ------------------------------------------------------------------

def random() -> float:
    """Drop-in for ``random.random()``."""
    rng = _active_rng.get()
    if rng is not None:
        return rng.random()
    return _random.random()


def randint(a: int, b: int) -> int:
    """Drop-in for ``random.randint()``."""
    rng = _active_rng.get()
    if rng is not None:
        return rng.randint(a, b)
    return _random.randint(a, b)


def uuid4() -> str:
    """Drop-in for ``uuid.uuid4()``, returns string form."""
    rng = _active_rng.get()
    if rng is not None:
        return rng.uuid4()
    return str(_uuid.uuid4())

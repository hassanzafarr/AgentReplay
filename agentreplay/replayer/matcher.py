"""Standalone hybrid matcher for pairing replay calls to recorded events.

Extracted from the Phase 1 interceptor so it can be reused by the replay
engine and divergence detector. The matching strategy is Decision D2:

  1. **Hash match** — content-hash the input, find events with the same hash.
  2. **Cursor fallback** — if multiple events share a hash (retry loops),
     use a per-hash cursor to pick the next one in recorded order.
  3. **Miss** — no matching event. The caller decides what to do: raise
     (strict replay) or record the divergence (diff mode).

The matcher also tracks statistics (hits, cursor-fallbacks, misses) so
the replay engine and CLI can report them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentreplay.schema.trace import EventType, Trace, TraceEvent


@dataclass
class MatchStats:
    """Counters for how calls were resolved during replay."""

    hash_hits: int = 0
    cursor_fallbacks: int = 0
    misses: int = 0

    @property
    def total(self) -> int:
        return self.hash_hits + self.cursor_fallbacks + self.misses

    @property
    def miss_rate(self) -> float:
        return self.misses / self.total if self.total > 0 else 0.0


@dataclass
class MatchResult:
    """Outcome of a single lookup attempt."""

    event: TraceEvent | None
    hit_type: str  # "hash", "cursor", "miss"


class TraceMatcher:
    """Pairs replay calls to recorded events via hybrid matching.

    Usage::

        matcher = TraceMatcher(recorded_trace)
        result = matcher.lookup(EventType.LLM_CALL, input_hash)
        if result.event is None:
            # divergence — no recorded response for this call
    """

    def __init__(self, trace: Trace) -> None:
        self._trace = trace
        self._cursors: dict[str, int] = {}  # per-(event_type, hash) cursors
        self._stats = MatchStats()

    @property
    def stats(self) -> MatchStats:
        return self._stats

    @property
    def trace(self) -> Trace:
        return self._trace

    def lookup(
        self,
        event_type: EventType,
        input_hash: str,
    ) -> MatchResult:
        """Find the next recorded event matching *event_type* and *input_hash*.

        Returns a ``MatchResult`` with the matched event (or ``None`` on miss).
        """
        # Find all events of this type with matching hash.
        candidates = [
            e for e in self._trace.events
            if e.event_type == event_type and e.hash == input_hash
        ]

        if not candidates:
            self._stats.misses += 1
            return MatchResult(event=None, hit_type="miss")

        # Per-hash cursor key includes event_type to avoid cross-type collisions.
        cursor_key = f"{event_type.value}:{input_hash}"
        cursor = self._cursors.get(cursor_key, 0)

        if cursor == 0 and len(candidates) == 1:
            # Common case: unique hash, direct hit.
            self._stats.hash_hits += 1
            self._cursors[cursor_key] = 1
            return MatchResult(event=candidates[0], hit_type="hash")

        # Multiple candidates or cursor > 0: cursor fallback.
        idx = min(cursor, len(candidates) - 1)
        self._cursors[cursor_key] = cursor + 1
        self._stats.cursor_fallbacks += 1
        return MatchResult(event=candidates[idx], hit_type="cursor")

    def lookup_by_seq(self, seq: int) -> TraceEvent | None:
        """Direct lookup by sequence number. Used for divergence alignment."""
        for e in self._trace.events:
            if e.seq == seq:
                return e
        return None

    def reset(self) -> None:
        """Reset cursors and stats for a fresh replay pass."""
        self._cursors.clear()
        self._stats = MatchStats()

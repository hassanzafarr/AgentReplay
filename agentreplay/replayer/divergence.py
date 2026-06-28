"""Divergence detection — compare two traces and report what changed.

This is the payoff feature (Decision D4). Given two traces (e.g., one from
old code, one from new code), produce a structured report showing exactly
what diverged: structural path changes, tool-call differences, and LLM
output differences.

Comparison tiers (in order of value, all free — no API calls):
1. **Structural** — did the agent take the same path? Same event types in
   the same order? An added/removed/reordered event is a structural divergence.
2. **Tool-call** — for matched tool events: same tool name? Same args?
3. **LLM output** — for matched LLM events: same prompt? Same output?

Semantic comparison (LLM-as-judge) is deliberately excluded from v1. It
reintroduces API cost and complexity. Structural + tool-call diffing is
where the real regressions hide, and it's free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import unified_diff
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from agentreplay.schema.trace import (
    EventType,
    LLMCallEvent,
    ToolCallEvent,
    Trace,
    TraceEvent,
)

# Only these event types signal a real code-path change. Clock/RNG events are
# always served identically on replay, so they never constitute a divergence.
_DIFFABLE_TYPES: frozenset[EventType] = frozenset({EventType.LLM_CALL, EventType.TOOL_CALL})


# ---------------------------------------------------------------------------
# Divergence types
# ---------------------------------------------------------------------------

class DivergenceLevel(str, Enum):
    """Severity of a divergence."""
    STRUCTURAL = "structural"
    TOOL_CALL = "tool_call"
    LLM_OUTPUT = "llm_output"


class StructuralDivergence(BaseModel):
    """The event sequence itself differs (added/removed/reordered events)."""
    position: int = Field(..., description="Index in the aligned sequence")
    description: str = ""
    event_a: str | None = None  # Event summary from trace A (or None if absent)
    event_b: str | None = None  # Event summary from trace B (or None if absent)


class ToolDivergence(BaseModel):
    """A tool was called differently between traces."""
    seq_a: int = Field(..., description="Sequence number in trace A")
    seq_b: int = Field(..., description="Sequence number in trace B")
    tool_name: str = ""
    description: str = ""
    args_diff: str = ""  # Unified diff of args


class LLMDivergence(BaseModel):
    """An LLM call produced different input or output between traces."""
    seq_a: int = Field(..., description="Sequence number in trace A")
    seq_b: int = Field(..., description="Sequence number in trace B")
    description: str = ""
    prompt_changed: bool = False
    output_changed: bool = False
    output_diff: str = ""  # Unified diff of output text


class DiffStats(BaseModel):
    """Summary counts."""
    total_events_a: int = 0
    total_events_b: int = 0
    structural: int = 0
    tool_call: int = 0
    llm_output: int = 0

    @property
    def total_divergences(self) -> int:
        return self.structural + self.tool_call + self.llm_output


class DivergenceReport(BaseModel):
    """Complete comparison result between two traces.

    This is the primary output of the divergence detector and the thing
    that gets printed by the CLI and displayed in the dashboard.
    """

    summary: str = ""
    is_identical: bool = True
    structural_divergences: list[StructuralDivergence] = Field(default_factory=list)
    tool_divergences: list[ToolDivergence] = Field(default_factory=list)
    llm_divergences: list[LLMDivergence] = Field(default_factory=list)
    stats: DiffStats = Field(default_factory=DiffStats)

    def format_report(self) -> str:
        """Human-readable text report for CLI output."""
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  AgentReplay — Divergence Report")
        lines.append("=" * 60)
        lines.append("")

        if self.is_identical:
            lines.append("✅ Traces are IDENTICAL. No divergences found.")
            lines.append(f"   Events compared: {self.stats.total_events_a}")
            return "\n".join(lines)

        lines.append(f"❌ {self.stats.total_divergences} divergence(s) found.")
        lines.append(f"   Trace A: {self.stats.total_events_a} events")
        lines.append(f"   Trace B: {self.stats.total_events_b} events")
        lines.append("")

        # Structural divergences.
        if self.structural_divergences:
            lines.append(f"── Structural ({len(self.structural_divergences)}) "
                         "─────────────────────────")
            for d in self.structural_divergences:
                lines.append(f"  [{d.position}] {d.description}")
                if d.event_a:
                    lines.append(f"      A: {d.event_a}")
                if d.event_b:
                    lines.append(f"      B: {d.event_b}")
            lines.append("")

        # Tool divergences.
        if self.tool_divergences:
            lines.append(f"── Tool Calls ({len(self.tool_divergences)}) "
                         "───────────────────────────")
            for d in self.tool_divergences:
                lines.append(f"  [{d.tool_name}] {d.description}")
                if d.args_diff:
                    lines.append(f"      {d.args_diff}")
            lines.append("")

        # LLM divergences.
        if self.llm_divergences:
            lines.append(f"── LLM Outputs ({len(self.llm_divergences)}) "
                         "──────────────────────────")
            for d in self.llm_divergences:
                flags = []
                if d.prompt_changed:
                    flags.append("prompt changed")
                if d.output_changed:
                    flags.append("output changed")
                lines.append(f"  [seq {d.seq_a}→{d.seq_b}] {', '.join(flags)}")
                if d.output_diff:
                    for diff_line in d.output_diff.split("\n")[:8]:
                        lines.append(f"      {diff_line}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Event helpers
# ---------------------------------------------------------------------------

def _event_summary(event: TraceEvent) -> str:
    """One-line summary of an event for display."""
    if event.event_type == EventType.LLM_CALL:
        prompt_preview = event.input_messages[0].content[:50] if event.input_messages else "?"
        return f"llm_call(seq={event.seq}, prompt=\"{prompt_preview}...\")"
    elif event.event_type == EventType.TOOL_CALL:
        return f"tool_call(seq={event.seq}, tool={event.tool_name})"
    elif event.event_type == EventType.CLOCK:
        return f"clock(seq={event.seq})"
    elif event.event_type == EventType.RANDOM:
        return f"random(seq={event.seq}, source={event.source})"
    return f"event(seq={event.seq}, type={event.event_type})"


def _text_diff(text_a: str, text_b: str, label_a: str = "A", label_b: str = "B") -> str:
    """Unified diff of two text strings."""
    diff = unified_diff(
        text_a.splitlines(keepends=True),
        text_b.splitlines(keepends=True),
        fromfile=label_a,
        tofile=label_b,
        lineterm="",
    )
    return "\n".join(diff)


# ---------------------------------------------------------------------------
# Core diffing
# ---------------------------------------------------------------------------

def diff_traces(trace_a: Trace, trace_b: Trace) -> DivergenceReport:
    """Compare two traces and produce a divergence report.

    This is the primary entry point for trace-vs-trace comparison::

        report = diff_traces(old_trace, new_trace)
        if not report.is_identical:
            print(report.format_report())

    The comparison is performed in three tiers:
    1. Structural — event type sequence alignment
    2. Tool calls — argument comparison for matched tool events
    3. LLM outputs — prompt/output comparison for matched LLM events
    """
    report = DivergenceReport()

    all_a = sorted(trace_a.events, key=lambda e: e.seq)
    all_b = sorted(trace_b.events, key=lambda e: e.seq)

    report.stats.total_events_a = len(all_a)
    report.stats.total_events_b = len(all_b)

    # Filter to diffable types only. Clock/RNG events are deterministic on
    # replay and never indicate a meaningful divergence.
    events_a = [e for e in all_a if e.event_type in _DIFFABLE_TYPES]
    events_b = [e for e in all_b if e.event_type in _DIFFABLE_TYPES]

    # Tier 1: Structural comparison (event type sequence).
    _compare_structural(events_a, events_b, report)

    # Tier 2 & 3: Pairwise comparison of matched events.
    _compare_paired_events(events_a, events_b, report)

    # Finalize.
    report.is_identical = report.stats.total_divergences == 0
    if report.is_identical:
        report.summary = f"Traces are identical ({len(events_a)} events)"
    else:
        report.summary = (
            f"{report.stats.total_divergences} divergence(s): "
            f"{report.stats.structural} structural, "
            f"{report.stats.tool_call} tool, "
            f"{report.stats.llm_output} LLM"
        )

    return report


def _compare_structural(
    events_a: list[TraceEvent],
    events_b: list[TraceEvent],
    report: DivergenceReport,
) -> None:
    """Tier 1: compare event type sequences."""
    types_a = [e.event_type.value for e in events_a]
    types_b = [e.event_type.value for e in events_b]

    if types_a == types_b:
        return  # Same structural path — no divergence.

    # Find positions where the sequences differ.
    max_len = max(len(types_a), len(types_b))
    for i in range(max_len):
        type_a = types_a[i] if i < len(types_a) else None
        type_b = types_b[i] if i < len(types_b) else None

        if type_a != type_b:
            div = StructuralDivergence(position=i)

            if type_a is None:
                div.description = f"Event added in trace B: {type_b}"
                div.event_b = _event_summary(events_b[i])
            elif type_b is None:
                div.description = f"Event removed in trace B (was in A): {type_a}"
                div.event_a = _event_summary(events_a[i])
            else:
                div.description = f"Event type changed: {type_a} → {type_b}"
                div.event_a = _event_summary(events_a[i])
                div.event_b = _event_summary(events_b[i])

            report.structural_divergences.append(div)
            report.stats.structural += 1


def _compare_paired_events(
    events_a: list[TraceEvent],
    events_b: list[TraceEvent],
    report: DivergenceReport,
) -> None:
    """Tier 2 & 3: pairwise comparison of events at matching positions."""
    for i in range(min(len(events_a), len(events_b))):
        ea = events_a[i]
        eb = events_b[i]

        # Only compare events of the same type.
        if ea.event_type != eb.event_type:
            continue  # Already caught by structural diff.

        if ea.event_type == EventType.TOOL_CALL:
            _compare_tool_events(ea, eb, report)
        elif ea.event_type == EventType.LLM_CALL:
            _compare_llm_events(ea, eb, report)


def _compare_tool_events(
    ea: ToolCallEvent,
    eb: ToolCallEvent,
    report: DivergenceReport,
) -> None:
    """Compare two tool call events."""
    if ea.tool_name != eb.tool_name:
        report.tool_divergences.append(ToolDivergence(
            seq_a=ea.seq,
            seq_b=eb.seq,
            tool_name=f"{ea.tool_name}→{eb.tool_name}",
            description=f"Tool name changed: {ea.tool_name} → {eb.tool_name}",
        ))
        report.stats.tool_call += 1
        return

    if ea.input_args != eb.input_args:
        import json
        args_a = json.dumps(ea.input_args, indent=2, default=str)
        args_b = json.dumps(eb.input_args, indent=2, default=str)
        report.tool_divergences.append(ToolDivergence(
            seq_a=ea.seq,
            seq_b=eb.seq,
            tool_name=ea.tool_name,
            description=f"Tool '{ea.tool_name}' called with different arguments",
            args_diff=_text_diff(args_a, args_b, "A", "B"),
        ))
        report.stats.tool_call += 1

    if ea.output != eb.output:
        report.tool_divergences.append(ToolDivergence(
            seq_a=ea.seq,
            seq_b=eb.seq,
            tool_name=ea.tool_name,
            description=f"Tool '{ea.tool_name}' returned different output",
        ))
        report.stats.tool_call += 1


def _compare_llm_events(
    ea: LLMCallEvent,
    eb: LLMCallEvent,
    report: DivergenceReport,
) -> None:
    """Compare two LLM call events."""
    prompt_a = "\n".join(m.content for m in ea.input_messages)
    prompt_b = "\n".join(m.content for m in eb.input_messages)
    prompt_changed = prompt_a != prompt_b

    output_changed = ea.output != eb.output

    if not prompt_changed and not output_changed:
        return  # Identical.

    output_diff = ""
    if output_changed:
        output_diff = _text_diff(ea.output, eb.output, "A", "B")

    desc_parts = []
    if prompt_changed:
        desc_parts.append("prompt changed")
    if output_changed:
        desc_parts.append("output changed")

    report.llm_divergences.append(LLMDivergence(
        seq_a=ea.seq,
        seq_b=eb.seq,
        description=", ".join(desc_parts),
        prompt_changed=prompt_changed,
        output_changed=output_changed,
        output_diff=output_diff,
    ))
    report.stats.llm_output += 1

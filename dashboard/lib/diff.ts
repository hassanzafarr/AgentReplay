// Port of agentreplay/replayer/divergence.py — runs in-browser, zero API calls.

import type {
  Trace,
  TraceEvent,
  LLMCallEvent,
  ToolCallEvent,
  DivergenceReport,
  StructuralDivergence,
  ToolDivergence,
  LLMDivergence,
  DiffStats,
} from "./types";

const DIFFABLE = new Set(["llm_call", "tool_call"]);

function eventSummary(e: TraceEvent): string {
  if (e.event_type === "llm_call") {
    const preview = e.input_messages[0]?.content.slice(0, 50) ?? "?";
    return `llm_call(seq=${e.seq}, prompt="${preview}...")`;
  }
  if (e.event_type === "tool_call") return `tool_call(seq=${e.seq}, tool=${e.tool_name})`;
  if (e.event_type === "clock") return `clock(seq=${e.seq})`;
  return `random(seq=${e.seq})`;
}

function unifiedDiff(a: string, b: string): string {
  const linesA = a.split("\n");
  const linesB = b.split("\n");
  const out: string[] = ["--- A", "+++ B"];
  const maxLen = Math.max(linesA.length, linesB.length);
  for (let i = 0; i < maxLen; i++) {
    const la = linesA[i];
    const lb = linesB[i];
    if (la === lb) {
      if (la !== undefined) out.push(` ${la}`);
    } else {
      if (la !== undefined) out.push(`-${la}`);
      if (lb !== undefined) out.push(`+${lb}`);
    }
  }
  return out.join("\n");
}

function compareStructural(
  eventsA: TraceEvent[],
  eventsB: TraceEvent[],
  divs: StructuralDivergence[],
  stats: DiffStats
) {
  const typesA = eventsA.map((e) => e.event_type);
  const typesB = eventsB.map((e) => e.event_type);
  if (typesA.join(",") === typesB.join(",")) return;

  const maxLen = Math.max(typesA.length, typesB.length);
  for (let i = 0; i < maxLen; i++) {
    const ta = typesA[i];
    const tb = typesB[i];
    if (ta === tb) continue;

    const div: StructuralDivergence = { position: i, description: "", event_a: null, event_b: null };
    if (ta === undefined) {
      div.description = `Event added in B: ${tb}`;
      div.event_b = eventSummary(eventsB[i]);
    } else if (tb === undefined) {
      div.description = `Event removed in B (was in A): ${ta}`;
      div.event_a = eventSummary(eventsA[i]);
    } else {
      div.description = `Event type changed: ${ta} → ${tb}`;
      div.event_a = eventSummary(eventsA[i]);
      div.event_b = eventSummary(eventsB[i]);
    }
    divs.push(div);
    stats.structural++;
  }
}

function compareToolEvents(
  ea: ToolCallEvent,
  eb: ToolCallEvent,
  divs: ToolDivergence[],
  stats: DiffStats
) {
  if (ea.tool_name !== eb.tool_name) {
    divs.push({
      seq_a: ea.seq,
      seq_b: eb.seq,
      tool_name: `${ea.tool_name}→${eb.tool_name}`,
      description: `Tool name changed: ${ea.tool_name} → ${eb.tool_name}`,
      args_diff: "",
    });
    stats.tool_call++;
    return;
  }

  const argsA = JSON.stringify(ea.input_args, null, 2);
  const argsB = JSON.stringify(eb.input_args, null, 2);
  if (argsA !== argsB) {
    divs.push({
      seq_a: ea.seq,
      seq_b: eb.seq,
      tool_name: ea.tool_name,
      description: `Tool '${ea.tool_name}' called with different arguments`,
      args_diff: unifiedDiff(argsA, argsB),
    });
    stats.tool_call++;
  }
  if (ea.output !== eb.output) {
    divs.push({
      seq_a: ea.seq,
      seq_b: eb.seq,
      tool_name: ea.tool_name,
      description: `Tool '${ea.tool_name}' returned different output`,
      args_diff: "",
    });
    stats.tool_call++;
  }
}

function compareLLMEvents(
  ea: LLMCallEvent,
  eb: LLMCallEvent,
  divs: LLMDivergence[],
  stats: DiffStats
) {
  const promptA = ea.input_messages.map((m) => m.content).join("\n");
  const promptB = eb.input_messages.map((m) => m.content).join("\n");
  const promptChanged = promptA !== promptB;
  const outputChanged = ea.output !== eb.output;
  if (!promptChanged && !outputChanged) return;

  divs.push({
    seq_a: ea.seq,
    seq_b: eb.seq,
    description: [promptChanged && "prompt changed", outputChanged && "output changed"]
      .filter(Boolean)
      .join(", "),
    prompt_changed: promptChanged,
    output_changed: outputChanged,
    output_diff: outputChanged ? unifiedDiff(ea.output, eb.output) : "",
  });
  stats.llm_output++;
}

export function diffTraces(traceA: Trace, traceB: Trace): DivergenceReport {
  const allA = [...traceA.events].sort((a, b) => a.seq - b.seq);
  const allB = [...traceB.events].sort((a, b) => a.seq - b.seq);

  const stats: DiffStats = {
    total_events_a: allA.length,
    total_events_b: allB.length,
    structural: 0,
    tool_call: 0,
    llm_output: 0,
  };

  const eventsA = allA.filter((e) => DIFFABLE.has(e.event_type));
  const eventsB = allB.filter((e) => DIFFABLE.has(e.event_type));

  const structuralDivs: StructuralDivergence[] = [];
  const toolDivs: ToolDivergence[] = [];
  const llmDivs: LLMDivergence[] = [];

  compareStructural(eventsA, eventsB, structuralDivs, stats);

  const minLen = Math.min(eventsA.length, eventsB.length);
  for (let i = 0; i < minLen; i++) {
    const ea = eventsA[i];
    const eb = eventsB[i];
    if (ea.event_type !== eb.event_type) continue;
    if (ea.event_type === "tool_call" && eb.event_type === "tool_call") {
      compareToolEvents(ea, eb, toolDivs, stats);
    } else if (ea.event_type === "llm_call" && eb.event_type === "llm_call") {
      compareLLMEvents(ea, eb, llmDivs, stats);
    }
  }

  const total = stats.structural + stats.tool_call + stats.llm_output;
  return {
    summary:
      total === 0
        ? `Traces identical (${eventsA.length} events)`
        : `${total} divergence(s): ${stats.structural} structural, ${stats.tool_call} tool, ${stats.llm_output} LLM`,
    is_identical: total === 0,
    structural_divergences: structuralDivs,
    tool_divergences: toolDivs,
    llm_divergences: llmDivs,
    stats,
  };
}

export function resolveBlobs(trace: Trace): Trace {
  const events = trace.events.map((e) => {
    if (e.event_type === "llm_call" && e.output_blob_key && trace.blobs[e.output_blob_key]) {
      return { ...e, output: trace.blobs[e.output_blob_key] };
    }
    return e;
  });
  return { ...trace, events };
}

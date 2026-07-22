"use client";

import type { DivergenceReport, Trace } from "@/lib/types";
import { diffTraces } from "@/lib/diff";
import { useMemo } from "react";

function DiffLine({ line }: { line: string }) {
  if (line.startsWith("+") && !line.startsWith("+++"))
    return <div className="bg-emerald-500/15 text-emerald-300">{line}</div>;
  if (line.startsWith("-") && !line.startsWith("---"))
    return <div className="bg-red-500/15 text-red-300">{line}</div>;
  if (line.startsWith("@") || line.startsWith("---") || line.startsWith("+++"))
    return <div className="text-fg-subtle">{line}</div>;
  return <div className="text-code-fg/70">{line}</div>;
}

function DiffBlock({ diff }: { diff: string }) {
  if (!diff) return null;
  return (
    <pre className="scroll-thin mt-2 max-h-56 overflow-auto rounded-lg bg-code-bg p-2 text-xs leading-relaxed">
      {diff.split("\n").map((line, i) => (
        <DiffLine key={i} line={line} />
      ))}
    </pre>
  );
}

function StatTile({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface-2 px-3 py-2.5 text-center">
      <div className={`text-2xl font-bold tabular-nums ${accent ?? "text-fg"}`}>{value}</div>
      <div className="mt-0.5 text-[11px] uppercase tracking-wide text-fg-subtle">{label}</div>
    </div>
  );
}

interface Props {
  traceA: Trace | null;
  traceB: Trace | null;
}

export default function DiffView({ traceA, traceB }: Props) {
  const report: DivergenceReport | null = useMemo(() => {
    if (!traceA || !traceB) return null;
    return diffTraces(traceA, traceB);
  }, [traceA, traceB]);

  if (!traceA || !traceB) {
    return (
      <div className="flex h-full min-h-48 flex-col items-center justify-center gap-2 p-8 text-center">
        <span className="text-2xl opacity-40">🔬</span>
        <p className="text-sm text-fg-subtle">Load two traces to compare them.</p>
      </div>
    );
  }

  if (!report) return null;
  const ok = report.is_identical;

  return (
    <div className="animate-fade-in flex flex-col gap-6 p-4">
      {/* Verdict banner */}
      <div
        className={`flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 ${
          ok
            ? "border-emerald-500/30 bg-emerald-500/10"
            : "border-red-500/30 bg-red-500/10"
        }`}
      >
        <span
          className={`grid h-8 w-8 place-items-center rounded-full text-sm ${
            ok ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"
          }`}
        >
          {ok ? "✓" : "≠"}
        </span>
        <div className="flex flex-col">
          <span className={`text-sm font-semibold ${ok ? "text-emerald-400" : "text-red-400"}`}>
            {ok ? "Traces identical" : "Divergence detected"}
          </span>
          <span className="text-xs text-fg-muted">{report.summary}</span>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <StatTile label="Events A" value={report.stats.total_events_a} />
        <StatTile label="Events B" value={report.stats.total_events_b} />
        <StatTile
          label="Structural"
          value={report.stats.structural}
          accent={report.stats.structural ? "text-red-400" : "text-fg"}
        />
        <StatTile
          label="Tool"
          value={report.stats.tool_call}
          accent={report.stats.tool_call ? "text-amber-400" : "text-fg"}
        />
        <StatTile
          label="LLM"
          value={report.stats.llm_output}
          accent={report.stats.llm_output ? "text-violet-400" : "text-fg"}
        />
      </div>

      {ok && (
        <p className="rounded-lg bg-surface-2 px-4 py-3 text-sm text-fg-muted">
          Replay reproduced the recording exactly — structurally and semantically identical. No
          regressions detected.
        </p>
      )}

      {report.structural_divergences.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-red-400">
            Structural · {report.structural_divergences.length}
          </h3>
          <div className="flex flex-col gap-2">
            {report.structural_divergences.map((d, i) => (
              <div
                key={i}
                className="rounded-lg border border-red-500/25 bg-red-500/5 p-3 text-sm"
              >
                <p className="font-medium text-fg">
                  [{d.position}] {d.description}
                </p>
                {d.event_a && (
                  <p className="mt-1 font-mono text-xs text-fg-muted">A: {d.event_a}</p>
                )}
                {d.event_b && <p className="font-mono text-xs text-fg-muted">B: {d.event_b}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      {report.tool_divergences.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-amber-400">
            Tool Calls · {report.tool_divergences.length}
          </h3>
          <div className="flex flex-col gap-2">
            {report.tool_divergences.map((d, i) => (
              <div
                key={i}
                className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-3 text-sm"
              >
                <p className="font-medium text-fg">
                  [{d.tool_name}] {d.description}
                </p>
                <DiffBlock diff={d.args_diff} />
              </div>
            ))}
          </div>
        </section>
      )}

      {report.llm_divergences.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-violet-400">
            LLM Outputs · {report.llm_divergences.length}
          </h3>
          <div className="flex flex-col gap-2">
            {report.llm_divergences.map((d, i) => (
              <div
                key={i}
                className="rounded-lg border border-violet-500/25 bg-violet-500/5 p-3 text-sm"
              >
                <p className="font-medium text-fg">
                  [seq {d.seq_a}→{d.seq_b}] {d.description}
                </p>
                <DiffBlock diff={d.output_diff} />
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

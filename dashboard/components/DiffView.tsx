"use client";

import type { DivergenceReport, Trace } from "@/lib/types";
import { diffTraces } from "@/lib/diff";
import { useMemo } from "react";

function DiffLine({ line }: { line: string }) {
  if (line.startsWith("+")) return <div className="bg-green-900/40 text-green-300">{line}</div>;
  if (line.startsWith("-")) return <div className="bg-red-900/40 text-red-300">{line}</div>;
  if (line.startsWith("@") || line.startsWith("---") || line.startsWith("+++"))
    return <div className="text-gray-500">{line}</div>;
  return <div className="text-gray-300">{line}</div>;
}

function DiffBlock({ diff }: { diff: string }) {
  if (!diff) return null;
  return (
    <pre className="mt-1 rounded bg-gray-900 p-2 text-xs overflow-auto max-h-48">
      {diff.split("\n").map((line, i) => (
        <DiffLine key={i} line={line} />
      ))}
    </pre>
  );
}

function StatusBadge({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${
        ok ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"
      }`}
    >
      {ok ? "✅ Identical" : "❌ Diverged"}
    </span>
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
      <div className="flex h-full items-center justify-center text-sm text-gray-400 italic">
        Load two traces to compare them.
      </div>
    );
  }

  if (!report) return null;

  return (
    <div className="flex flex-col gap-6 p-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <StatusBadge ok={report.is_identical} />
        <span className="text-sm text-gray-600">{report.summary}</span>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {(
          [
            ["Events A", report.stats.total_events_a],
            ["Events B", report.stats.total_events_b],
            ["Structural", report.stats.structural],
            ["Tool", report.stats.tool_call],
            ["LLM", report.stats.llm_output],
          ] as [string, number][]
        ).map(([label, val]) => (
          <div key={label} className="rounded-lg border bg-gray-50 px-3 py-2 text-center">
            <div className="text-xl font-bold text-gray-800">{val}</div>
            <div className="text-xs text-gray-500">{label}</div>
          </div>
        ))}
      </div>

      {report.is_identical && (
        <p className="text-sm text-emerald-700">
          Traces are structurally and semantically identical. No regressions detected.
        </p>
      )}

      {/* Structural divergences */}
      {report.structural_divergences.length > 0 && (
        <section>
          <h3 className="mb-2 font-semibold text-red-700">
            Structural ({report.structural_divergences.length})
          </h3>
          <div className="flex flex-col gap-2">
            {report.structural_divergences.map((d, i) => (
              <div key={i} className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm">
                <p className="font-medium text-red-800">[{d.position}] {d.description}</p>
                {d.event_a && <p className="text-xs font-mono text-gray-600 mt-1">A: {d.event_a}</p>}
                {d.event_b && <p className="text-xs font-mono text-gray-600">B: {d.event_b}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Tool divergences */}
      {report.tool_divergences.length > 0 && (
        <section>
          <h3 className="mb-2 font-semibold text-amber-700">
            Tool Calls ({report.tool_divergences.length})
          </h3>
          <div className="flex flex-col gap-2">
            {report.tool_divergences.map((d, i) => (
              <div key={i} className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
                <p className="font-medium text-amber-800">[{d.tool_name}] {d.description}</p>
                <DiffBlock diff={d.args_diff} />
              </div>
            ))}
          </div>
        </section>
      )}

      {/* LLM divergences */}
      {report.llm_divergences.length > 0 && (
        <section>
          <h3 className="mb-2 font-semibold text-violet-700">
            LLM Outputs ({report.llm_divergences.length})
          </h3>
          <div className="flex flex-col gap-2">
            {report.llm_divergences.map((d, i) => (
              <div key={i} className="rounded-lg border border-violet-200 bg-violet-50 p-3 text-sm">
                <p className="font-medium text-violet-800">
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

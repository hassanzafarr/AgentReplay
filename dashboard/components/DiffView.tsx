"use client";

import type { DivergenceReport, Trace, TraceEvent } from "@/lib/types";
import { diffTraces } from "@/lib/diff";
import { EVENT_STYLES } from "@/lib/events";
import { useMemo } from "react";
import { CompareIcon } from "./Icons";
import PunchField from "./PunchField";
import { eventTitle } from "./Timeline";
import { punchSource } from "@/lib/punch";

/* Unified diff on plain listing paper: struck red for the baseline, green for the candidate,
   so the change reads by mark and colour together. */
function DiffLine({ line }: { line: string }) {
  if (line.startsWith("+") && !line.startsWith("+++"))
    return <div className="bg-add-bg text-add-ink">{line}</div>;
  if (line.startsWith("-") && !line.startsWith("---"))
    return <div className="bg-del-bg text-del-ink line-through decoration-del-ink/35">{line}</div>;
  if (line.startsWith("@") || line.startsWith("---") || line.startsWith("+++"))
    return <div className="text-ink-muted">{line}</div>;
  return <div className="text-ink">{line}</div>;
}

function DiffBlock({ diff }: { diff: string }) {
  if (!diff) return null;
  // Wrap instead of scrolling sideways: the changed words are often far past the fold.
  return (
    <pre className="listing-plain scroll-thin mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words border-y border-card-line px-3 py-2 font-mono text-[12.5px] leading-5">
      {diff.split("\n").map((line, i) => (
        <DiffLine key={i} line={line} />
      ))}
    </pre>
  );
}

/* One deck as a column of slim cards; cards that diverge slide out toward the other deck. */
function MiniDeck({
  label,
  events,
  mismatched,
  side,
}: {
  label: string;
  events: TraceEvent[];
  mismatched: Set<number>;
  side: "a" | "b";
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <h3 className="cardprint text-xs text-on-desk-muted">{label}</h3>
      <ol className="flex flex-col gap-1">
        {events.map((e) => {
          const style = EVENT_STYLES[e.event_type] ?? EVENT_STYLES.clock;
          const off = mismatched.has(e.seq);
          return (
            <li
              key={e.seq}
              className={`transition-transform duration-200 ease-out motion-reduce:transform-none ${
                off ? (side === "a" ? "translate-x-2.5" : "-translate-x-2.5") : ""
              } ${off ? "drop-shadow-[0_4px_6px_rgb(0_0_0/0.3)]" : ""}`}
            >
              <div className="punchcard flex items-stretch">
                <span aria-hidden className={`w-1.5 shrink-0 ${style.stripe}`} />
                {/* Band sits under the text on narrow decks and beside it from md, never hidden. */}
                <div className="flex min-w-0 flex-1 flex-col gap-2 py-2 pl-2.5 pr-2.5 md:flex-row md:items-center">
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="flex items-baseline gap-2">
                      <span className="font-mono text-xs tabular-nums text-print">
                        {String(e.seq).padStart(2, "0")}
                      </span>
                      <span className={`cardprint text-[11px] ${style.ink}`}>{style.label}</span>
                      {off && (
                        <span
                          className="cardprint ml-auto text-xs font-extrabold text-print"
                          title="Diverges from the other deck"
                        >
                          ≠<span className="sr-only"> diverges</span>
                        </span>
                      )}
                    </span>
                    <span className="line-clamp-2 text-[13px] font-semibold leading-snug text-ink">{eventTitle(e)}</span>
                  </div>
                  <PunchField source={punchSource(e)} />
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function TierHeading({ stripe, children }: { stripe: string; children: React.ReactNode }) {
  return (
    <h3 className="mb-2 flex items-center gap-2 text-sm font-bold text-on-desk">
      <span aria-hidden className={`h-3 w-3 ${stripe}`} />
      {children}
    </h3>
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

  const decks = useMemo(() => {
    if (!traceA || !traceB || !report) return null;
    const sortA = [...traceA.events].sort((x, y) => x.seq - y.seq);
    const sortB = [...traceB.events].sort((x, y) => x.seq - y.seq);
    const diffable = (evs: TraceEvent[]) => evs.filter((e) => e.event_type === "llm_call" || e.event_type === "tool_call");
    const offA = new Set<number>();
    const offB = new Set<number>();
    for (const d of [...report.tool_divergences, ...report.llm_divergences]) {
      offA.add(d.seq_a);
      offB.add(d.seq_b);
    }
    // Structural divergences point at positions in the diffable (LLM + tool) sequence.
    const dA = diffable(sortA);
    const dB = diffable(sortB);
    for (const d of report.structural_divergences) {
      if (dA[d.position]) offA.add(dA[d.position].seq);
      if (dB[d.position]) offB.add(dB[d.position].seq);
    }
    return { sortA, sortB, offA, offB };
  }, [traceA, traceB, report]);

  if (!traceA || !traceB || !report || !decks) {
    return (
      <div className="flex min-h-48 flex-col items-center justify-center gap-2 border border-dashed border-desk-line p-8 text-center">
        <CompareIcon className="h-6 w-6 text-on-desk-muted" />
        <p className="text-sm text-on-desk-muted">Load two decks to compare them card by card.</p>
      </div>
    );
  }

  const ok = report.is_identical;
  const { stats } = report;

  return (
    <div className="animate-deal flex flex-col gap-8">
      {/* Verdict */}
      <div role="status" className="punchcard">
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 px-6 py-4">
          <span className={`cardprint text-2xl font-extrabold ${ok ? "text-ev-llm-ink" : "text-print"}`}>
            {ok ? "Decks match" : "Decks diverge"}
          </span>
          <span className="font-mono text-xs text-ink-muted">
            {stats.total_events_a} cards vs {stats.total_events_b} cards · structural {stats.structural} · tool{" "}
            {stats.tool_call} · LLM {stats.llm_output}
          </span>
          {ok && (
            <p className="w-full text-sm text-ink">
              Replay matched the recording on all three tiers: graph path, tool calls and LLM calls. No regressions
              detected.
            </p>
          )}
        </div>
      </div>

      {/* The two decks, aligned card for card */}
      <div className="grid grid-cols-2 gap-4 sm:gap-8">
        <MiniDeck label="Deck A · baseline" events={decks.sortA} mismatched={decks.offA} side="a" />
        <MiniDeck label="Deck B · candidate" events={decks.sortB} mismatched={decks.offB} side="b" />
      </div>

      {report.structural_divergences.length > 0 && (
        <section>
          <TierHeading stripe="bg-print">Structural · {report.structural_divergences.length}</TierHeading>
          <div className="flex flex-col gap-2">
            {report.structural_divergences.map((d, i) => (
              <div key={i} className="punchcard px-5 py-3 text-sm">
                <p className="font-semibold text-ink">
                  <span className="font-mono text-print">[{d.position}]</span> {d.description}
                </p>
                {d.event_a && <p className="mt-1 font-mono text-xs text-ink-muted">A: {d.event_a}</p>}
                {d.event_b && <p className="font-mono text-xs text-ink-muted">B: {d.event_b}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      {report.tool_divergences.length > 0 && (
        <section>
          <TierHeading stripe="bg-ev-tool">Tool calls · {report.tool_divergences.length}</TierHeading>
          <div className="flex flex-col gap-2">
            {report.tool_divergences.map((d, i) => (
              <div key={i} className="punchcard px-5 py-3 text-sm">
                <p className="font-semibold text-ink">
                  <span className="font-mono text-print">
                    [{d.seq_a}→{d.seq_b}]
                  </span>{" "}
                  {d.description}
                </p>
                <DiffBlock diff={d.args_diff} />
              </div>
            ))}
          </div>
        </section>
      )}

      {report.llm_divergences.length > 0 && (
        <section>
          <TierHeading stripe="bg-ev-llm">LLM calls · {report.llm_divergences.length}</TierHeading>
          <div className="flex flex-col gap-2">
            {report.llm_divergences.map((d, i) => (
              <div key={i} className="punchcard px-5 py-3 text-sm">
                <p className="font-semibold text-ink">
                  <span className="font-mono text-print">
                    [{d.seq_a}→{d.seq_b}]
                  </span>{" "}
                  {d.description}
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

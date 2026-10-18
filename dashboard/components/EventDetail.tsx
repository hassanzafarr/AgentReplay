"use client";

import { useState } from "react";
import type { TraceEvent } from "@/lib/types";
import { EVENT_STYLES } from "@/lib/events";
import { PointerIcon } from "./Icons";
import PunchField from "./PunchField";
import { punchSource } from "@/lib/punch";

function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const flash = (s: "copied" | "failed") => {
    setState(s);
    setTimeout(() => setState("idle"), 1400);
  };
  return (
    <button
      type="button"
      aria-live="polite"
      onClick={() => {
        // Clipboard API is missing on insecure origins (e.g. a LAN IP); say so instead of failing silently.
        if (!navigator.clipboard) return flash("failed");
        navigator.clipboard.writeText(text).then(() => flash("copied"), () => flash("failed"));
      }}
      className="cardprint min-h-6 border border-card-line px-2 text-[11px] text-ink-muted transition-colors hover:border-ink hover:text-ink"
    >
      {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : "Copy"}
    </button>
  );
}

function Field({
  label,
  action,
  children,
}: {
  label: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="cardprint text-[11px] text-ink-muted">{label}</span>
        {action}
      </div>
      {children}
    </div>
  );
}

/* Long text prints as a line-printer listing; very long text is cut with a count. */
function Listing({ text, maxLines = 24 }: { text: string; maxLines?: number }) {
  const lines = text.split("\n");
  const clipped = lines.length > maxLines;
  return (
    <pre className="listing scroll-thin max-h-80 overflow-auto whitespace-pre-wrap break-words border-y border-card-line px-3 py-2 font-mono text-[12.5px]">
      {lines.slice(0, maxLines).join("\n")}
      {clipped && <span className="text-ink-muted">{"\n"}… {lines.length - maxLines} more lines</span>}
    </pre>
  );
}

interface Props {
  event: TraceEvent | null;
}

export default function EventDetail({ event }: Props) {
  if (!event) {
    return (
      <div className="punchcard flex min-h-56 flex-col items-center justify-center gap-2 p-8 text-center">
        <PointerIcon className="h-6 w-6 text-ink-muted" />
        <p className="text-sm text-ink-muted">Pick a card from the deck to print its listing.</p>
      </div>
    );
  }

  const style = EVENT_STYLES[event.event_type] ?? EVENT_STYLES.clock;

  return (
    <article className="punchcard animate-deal flex" key={event.seq} aria-label={`${style.long}, seq ${event.seq}`}>
      <span aria-hidden className={`w-2 shrink-0 ${style.stripe}`} />
      <div className="flex min-w-0 flex-1 flex-col gap-4 p-5">
        <header className="flex items-start gap-4 border-b-2 border-ink pb-3">
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <div className="flex flex-col">
              <span className="font-mono text-xs text-print">SEQ {String(event.seq).padStart(2, "0")}</span>
              <h3 className="cardprint text-2xl font-extrabold leading-tight tracking-wide text-ink">{style.long}</h3>
            </div>
            <div className="flex flex-wrap gap-1.5 font-mono text-[11px] text-ink-muted">
            {/* Names the band: it punches a digest of input + answer, not the raw input hash. */}
            <span className="border border-ink-muted/60 px-1.5 text-ink" title="Digest of this event's input and recorded answer">
              punched {punchSource(event).slice(0, 12).toUpperCase()}
            </span>
            {event.hash && <span className="border border-card-line px-1.5">hash {event.hash.slice(0, 10)}…</span>}
            {(event.event_type === "llm_call" || event.event_type === "tool_call") && (
              <>
                {event.node && <span className="border border-card-line px-1.5">node {event.node}</span>}
                {event.duration_ms != null && (
                  <span className="border border-card-line px-1.5">{Math.round(event.duration_ms)} ms</span>
                )}
              </>
            )}
            </div>
          </div>
          <PunchField source={punchSource(event)} />
        </header>

        {event.event_type === "llm_call" && (
          <>
            <Field label="Model">
              <span className="font-mono text-sm text-ink">{event.model_id ?? event.model_name}</span>
            </Field>
            {event.usage && (
              <Field label="Tokens">
                <span className="font-mono text-sm text-ink">
                  {event.usage.input_tokens} in → {event.usage.output_tokens} out
                  {event.usage.cache_read_tokens != null && ` (${event.usage.cache_read_tokens} cached)`}
                </span>
              </Field>
            )}
            <Field label="Prompt">
              <div className="flex flex-col gap-2">
                {event.input_messages.map((m, i) => (
                  <div key={i} className="flex flex-col gap-1">
                    <span className="font-mono text-[11px] text-print">[{m.role ?? m.type ?? "msg"}]</span>
                    <Listing text={m.content} />
                  </div>
                ))}
              </div>
            </Field>
            <Field label="Response" action={<CopyButton text={event.output} />}>
              <Listing text={event.output} />
            </Field>
            {Object.keys(event.kwargs ?? {}).length > 0 && (
              <Field label="kwargs">
                <Listing text={JSON.stringify(event.kwargs, null, 2)} />
              </Field>
            )}
          </>
        )}

        {event.event_type === "tool_call" && (
          <>
            <Field label="Tool">
              <span className="font-mono text-sm text-ink">{event.tool_name}</span>
            </Field>
            <Field label="Input args" action={<CopyButton text={JSON.stringify(event.input_args, null, 2)} />}>
              <Listing text={JSON.stringify(event.input_args, null, 2)} />
            </Field>
            {event.error ? (
              <Field label="Error">
                <pre className="listing-plain overflow-auto whitespace-pre-wrap border border-print px-3 py-2 font-mono text-[12.5px] text-del-ink">
                  {event.error}
                </pre>
              </Field>
            ) : (
              <Field label="Output" action={<CopyButton text={String(event.output ?? "")} />}>
                <Listing text={String(event.output ?? "(null)")} />
              </Field>
            )}
          </>
        )}

        {event.event_type === "clock" && (
          <Field label="Recorded time">
            <span className="font-mono text-sm text-ink">{event.recorded_time}</span>
          </Field>
        )}

        {event.event_type === "random" && (
          <>
            <Field label="Source">
              <span className="font-mono text-sm text-ink">{event.source}</span>
            </Field>
            <Field label="Value">
              <span className="break-all font-mono text-sm text-ink">{event.value}</span>
            </Field>
          </>
        )}

        <p className="mt-auto border-t border-card-line pt-3 font-mono text-[11px] text-ink-muted">ts {event.ts}</p>
      </div>
    </article>
  );
}

"use client";

import { useState } from "react";
import type { TraceEvent } from "@/lib/types";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        });
      }}
      className="rounded px-1.5 py-0.5 text-[10px] font-medium text-fg-subtle ring-1 ring-inset ring-border transition-colors hover:text-fg hover:ring-border-strong"
    >
      {copied ? "copied ✓" : "copy"}
    </button>
  );
}

function Section({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-fg-subtle">
          {title}
        </span>
        {action}
      </div>
      {children}
    </div>
  );
}

function CodeBlock({ text, maxLines = 24 }: { text: string; maxLines?: number }) {
  const lines = text.split("\n");
  const shown = lines.slice(0, maxLines);
  const clipped = lines.length > maxLines;
  return (
    <pre className="scroll-thin max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-code-bg p-3 text-xs leading-relaxed text-code-fg">
      {shown.join("\n")}
      {clipped && (
        <span className="text-fg-subtle">{"\n"}… ({lines.length - maxLines} more lines)</span>
      )}
    </pre>
  );
}

interface Props {
  event: TraceEvent | null;
}

export default function EventDetail({ event }: Props) {
  if (!event) {
    return (
      <div className="flex h-full min-h-48 flex-col items-center justify-center gap-2 p-8 text-center">
        <span className="text-2xl opacity-40">👈</span>
        <p className="text-sm text-fg-subtle">Select an event to inspect its payload.</p>
      </div>
    );
  }

  return (
    <div className="animate-fade-in flex flex-col gap-4 p-4" key={event.seq}>
      <div className="flex flex-wrap items-center gap-2 border-b border-border pb-3">
        <span className="font-mono text-sm font-bold text-fg">{event.event_type}</span>
        <span className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[11px] text-fg-muted">
          seq {event.seq}
        </span>
        {event.hash && (
          <span className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[11px] text-fg-subtle">
            {event.hash.slice(0, 10)}…
          </span>
        )}
      </div>

      {event.event_type === "llm_call" && (
        <>
          <Section title="Model">
            <span className="font-mono text-sm text-fg">{event.model_name}</span>
          </Section>
          <Section title="Prompt">
            <div className="flex flex-col gap-2">
              {event.input_messages.map((m, i) => (
                <div key={i} className="flex flex-col gap-1">
                  <span className="font-mono text-[11px] text-accent">
                    [{m.role ?? m.type ?? "msg"}]
                  </span>
                  <CodeBlock text={m.content} />
                </div>
              ))}
            </div>
          </Section>
          <Section title="Response" action={<CopyButton text={event.output} />}>
            <CodeBlock text={event.output} />
          </Section>
          {Object.keys(event.kwargs ?? {}).length > 0 && (
            <Section title="kwargs">
              <CodeBlock text={JSON.stringify(event.kwargs, null, 2)} />
            </Section>
          )}
        </>
      )}

      {event.event_type === "tool_call" && (
        <>
          <Section title="Tool">
            <span className="font-mono text-sm text-fg">{event.tool_name}</span>
          </Section>
          <Section
            title="Input args"
            action={<CopyButton text={JSON.stringify(event.input_args, null, 2)} />}
          >
            <CodeBlock text={JSON.stringify(event.input_args, null, 2)} />
          </Section>
          {event.error ? (
            <Section title="Error">
              <pre className="scroll-thin overflow-auto whitespace-pre-wrap rounded-lg bg-red-950/80 p-3 text-xs text-red-200 ring-1 ring-red-500/30">
                {event.error}
              </pre>
            </Section>
          ) : (
            <Section title="Output" action={<CopyButton text={String(event.output ?? "")} />}>
              <CodeBlock text={String(event.output ?? "(null)")} />
            </Section>
          )}
        </>
      )}

      {event.event_type === "clock" && (
        <Section title="Recorded time">
          <span className="font-mono text-sm text-fg">{event.recorded_time}</span>
        </Section>
      )}

      {event.event_type === "random" && (
        <>
          <Section title="Source">
            <span className="font-mono text-sm text-fg">{event.source}</span>
          </Section>
          <Section title="Value">
            <span className="break-all font-mono text-sm text-fg">{event.value}</span>
          </Section>
        </>
      )}

      <p className="mt-auto border-t border-border pt-3 font-mono text-[11px] text-fg-subtle">
        ts: {event.ts}
      </p>
    </div>
  );
}

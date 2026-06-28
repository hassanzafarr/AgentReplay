"use client";

import type { TraceEvent } from "@/lib/types";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</span>
      {children}
    </div>
  );
}

function CodeBlock({ text, maxLines = 20 }: { text: string; maxLines?: number }) {
  const lines = text.split("\n");
  const shown = lines.slice(0, maxLines);
  const clipped = lines.length > maxLines;
  return (
    <pre className="rounded-md bg-gray-900 p-3 text-xs text-gray-100 overflow-auto max-h-64 whitespace-pre-wrap">
      {shown.join("\n")}
      {clipped && <span className="text-gray-500">{"\n"}… ({lines.length - maxLines} more lines)</span>}
    </pre>
  );
}

interface Props {
  event: TraceEvent | null;
}

export default function EventDetail({ event }: Props) {
  if (!event) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-400 italic">
        Select an event to inspect it.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-2">
        <span className="text-lg font-bold font-mono text-gray-800">{event.event_type}</span>
        <span className="text-xs text-gray-400 font-mono">seq={event.seq}</span>
        <span className="text-xs text-gray-400 font-mono">hash={event.hash?.slice(0, 12)}…</span>
      </div>

      {event.event_type === "llm_call" && (
        <>
          <Section title="Model">
            <span className="font-mono text-sm text-gray-700">{event.model_name}</span>
          </Section>
          <Section title="Prompt">
            {event.input_messages.map((m, i) => (
              <div key={i} className="flex flex-col gap-1">
                <span className="text-xs font-mono text-gray-500">[{m.role}]</span>
                <CodeBlock text={m.content} />
              </div>
            ))}
          </Section>
          <Section title="Response">
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
            <span className="font-mono text-sm text-gray-700">{event.tool_name}</span>
          </Section>
          <Section title="Input">
            <CodeBlock text={JSON.stringify(event.input_args, null, 2)} />
          </Section>
          {event.error ? (
            <Section title="Error">
              <pre className="rounded-md bg-red-900 p-3 text-xs text-red-100 overflow-auto whitespace-pre-wrap">
                {event.error}
              </pre>
            </Section>
          ) : (
            <Section title="Output">
              <CodeBlock text={String(event.output ?? "(null)")} />
            </Section>
          )}
        </>
      )}

      {event.event_type === "clock" && (
        <Section title="Recorded time">
          <span className="font-mono text-sm text-gray-700">{event.recorded_time}</span>
        </Section>
      )}

      {event.event_type === "random" && (
        <>
          <Section title="Source">
            <span className="font-mono text-sm text-gray-700">{event.source}</span>
          </Section>
          <Section title="Value">
            <span className="font-mono text-sm text-gray-700">{event.value}</span>
          </Section>
        </>
      )}

      <p className="text-xs text-gray-400 font-mono mt-auto">ts: {event.ts}</p>
    </div>
  );
}

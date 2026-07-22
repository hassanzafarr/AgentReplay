"use client";

import type { TraceEvent } from "@/lib/types";

type Style = { dot: string; chip: string; label: string };

// Accent hues tuned to stay legible in both light and dark themes.
const EVENT_STYLES: Record<string, Style> = {
  llm_call: {
    dot: "bg-violet-500",
    chip: "bg-violet-500/10 text-violet-600 dark:text-violet-300 ring-violet-500/25",
    label: "LLM",
  },
  tool_call: {
    dot: "bg-emerald-500",
    chip: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300 ring-emerald-500/25",
    label: "TOOL",
  },
  clock: {
    dot: "bg-sky-500",
    chip: "bg-sky-500/10 text-sky-600 dark:text-sky-300 ring-sky-500/25",
    label: "CLOCK",
  },
  random: {
    dot: "bg-amber-500",
    chip: "bg-amber-500/10 text-amber-600 dark:text-amber-300 ring-amber-500/25",
    label: "RNG",
  },
};

function eventTitle(e: TraceEvent): string {
  if (e.event_type === "llm_call") {
    const human = e.input_messages.find((m) => (m.role ?? m.type) !== "system");
    const preview = (human ?? e.input_messages[0])?.content.slice(0, 72) ?? "";
    return preview ? `${preview}${preview.length === 72 ? "…" : ""}` : "(empty prompt)";
  }
  if (e.event_type === "tool_call") return e.tool_name + "()";
  if (e.event_type === "clock") return new Date(e.recorded_time).toLocaleTimeString();
  if (e.event_type === "random") return `${e.source} → ${e.value.slice(0, 24)}…`;
  return "";
}

interface Props {
  events: TraceEvent[];
  selectedSeq?: number;
  onSelect?: (event: TraceEvent) => void;
}

export default function Timeline({ events, selectedSeq, onSelect }: Props) {
  const sorted = [...events].sort((a, b) => a.seq - b.seq);

  if (sorted.length === 0) {
    return <p className="p-4 text-sm text-fg-subtle italic">No events match.</p>;
  }

  return (
    <ol className="relative flex flex-col">
      {/* vertical rail connecting the dots */}
      <span
        aria-hidden
        className="absolute left-[1.15rem] top-3 bottom-3 w-px bg-border"
      />
      {sorted.map((e) => {
        const style = EVENT_STYLES[e.event_type] ?? EVENT_STYLES.clock;
        const isSelected = e.seq === selectedSeq;
        return (
          <li key={e.seq}>
            <button
              onClick={() => onSelect?.(e)}
              className={`group relative flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors ${
                isSelected
                  ? "bg-accent/10 ring-1 ring-accent/40"
                  : "hover:bg-surface-3"
              }`}
            >
              <span className="relative z-10 grid h-6 w-6 shrink-0 place-items-center">
                <span
                  className={`h-2.5 w-2.5 rounded-full ${style.dot} ${
                    isSelected ? "ring-4 ring-accent/20" : ""
                  }`}
                />
              </span>
              <span className="w-8 shrink-0 font-mono text-[11px] tabular-nums text-fg-subtle">
                {String(e.seq).padStart(2, "0")}
              </span>
              <span
                className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ring-1 ring-inset ${style.chip}`}
              >
                {style.label}
              </span>
              <span className="truncate text-[13px] text-fg-muted group-hover:text-fg">
                {eventTitle(e)}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

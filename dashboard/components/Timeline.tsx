"use client";

import type { TraceEvent } from "@/lib/types";

const EVENT_STYLES: Record<string, { bg: string; border: string; label: string }> = {
  llm_call:  { bg: "bg-violet-100", border: "border-violet-400", label: "LLM" },
  tool_call: { bg: "bg-emerald-100", border: "border-emerald-400", label: "TOOL" },
  clock:     { bg: "bg-sky-100",    border: "border-sky-400",    label: "CLOCK" },
  random:    { bg: "bg-amber-100",  border: "border-amber-400",  label: "RNG" },
};

function eventTitle(e: TraceEvent): string {
  if (e.event_type === "llm_call") {
    const preview = e.input_messages[0]?.content.slice(0, 60) ?? "";
    return preview ? `"${preview}${preview.length === 60 ? "…" : ""}"` : "(empty prompt)";
  }
  if (e.event_type === "tool_call") return e.tool_name;
  if (e.event_type === "clock") return new Date(e.recorded_time).toLocaleTimeString();
  if (e.event_type === "random") return `${e.source} → ${e.value.slice(0, 20)}`;
  return "";
}

interface Props {
  events: TraceEvent[];
  selectedSeq?: number;
  onSelect?: (event: TraceEvent) => void;
}

export default function Timeline({ events, selectedSeq, onSelect }: Props) {
  const sorted = [...events].sort((a, b) => a.seq - b.seq);

  return (
    <div className="flex flex-col gap-1">
      {sorted.map((e) => {
        const style = EVENT_STYLES[e.event_type] ?? EVENT_STYLES.clock;
        const isSelected = e.seq === selectedSeq;
        return (
          <button
            key={e.seq}
            onClick={() => onSelect?.(e)}
            className={`
              flex items-start gap-3 rounded-lg border px-3 py-2 text-left text-sm
              transition-all hover:brightness-95
              ${style.bg} ${style.border}
              ${isSelected ? "ring-2 ring-offset-1 ring-violet-500 brightness-95" : ""}
            `}
          >
            <span className="mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-xs font-mono font-bold bg-white/60">
              {String(e.seq).padStart(3, "0")}
            </span>
            <span
              className={`
                shrink-0 rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide
                ${style.bg} border ${style.border}
              `}
            >
              {style.label}
            </span>
            <span className="truncate font-mono text-xs text-gray-700">{eventTitle(e)}</span>
          </button>
        );
      })}
      {sorted.length === 0 && (
        <p className="text-sm text-gray-400 italic">No events.</p>
      )}
    </div>
  );
}

"use client";

import type { TraceEvent } from "@/lib/types";
import { EVENT_STYLES } from "@/lib/events";
import { punchSource } from "@/lib/punch";
import PunchField from "./PunchField";

export function eventTitle(e: TraceEvent): string {
  if (e.event_type === "llm_call") {
    const human = e.input_messages.find((m) => (m.role ?? m.type) !== "system");
    const preview = (human ?? e.input_messages[0])?.content.slice(0, 140) ?? "";
    return preview ? `${preview}${preview.length === 140 ? "…" : ""}` : "(empty prompt)";
  }
  if (e.event_type === "tool_call") return e.tool_name + "()";
  if (e.event_type === "clock") return new Date(e.recorded_time).toLocaleTimeString();
  if (e.event_type === "random") return `${e.source} → ${e.value}`;
  return "";
}

function cardMeta(e: TraceEvent): string | null {
  if ((e.event_type === "llm_call" || e.event_type === "tool_call") && e.duration_ms != null) {
    return `${Math.round(e.duration_ms)} ms`;
  }
  if (e.event_type === "llm_call") return e.model_id ?? e.model_name;
  return null;
}

interface Props {
  events: TraceEvent[];
  selectedSeq?: number;
  onSelect?: (event: TraceEvent) => void;
}

export default function Timeline({ events, selectedSeq, onSelect }: Props) {
  const sorted = [...events].sort((a, b) => a.seq - b.seq);

  if (sorted.length === 0) {
    return <p className="px-1 py-6 text-sm text-on-desk-muted">No cards match the active filters.</p>;
  }

  // Up/Down step through the deck and select as they go, so a long run reads from the keyboard.
  const onKeyDown = (e: React.KeyboardEvent<HTMLOListElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const buttons = [...e.currentTarget.querySelectorAll<HTMLButtonElement>("button[data-seq]")];
    const i = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (i === -1) return;
    e.preventDefault();
    const next = buttons[Math.min(buttons.length - 1, Math.max(0, i + (e.key === "ArrowDown" ? 1 : -1)))];
    next.focus();
    next.click();
  };

  return (
    <ol className="flex flex-col gap-2 pr-4" aria-label="Deck of trace events" onKeyDown={onKeyDown}>
      {sorted.map((e, i) => {
        const style = EVENT_STYLES[e.event_type] ?? EVENT_STYLES.clock;
        const meta = cardMeta(e);
        return (
          <li key={e.seq} className="animate-deal" style={{ animationDelay: `${Math.min(i, 12) * 22}ms` }}>
            <button
              type="button"
              data-seq={e.seq}
              aria-pressed={e.seq === selectedSeq}
              onClick={() => onSelect?.(e)}
              className="deck-card group block w-full text-left"
            >
              <span className="punchcard flex items-stretch transition-colors group-hover:bg-card-2">
                <span aria-hidden className={`w-2 shrink-0 ${style.stripe}`} />
                <span className="flex min-w-0 flex-1 flex-col gap-1 py-3 pl-3 pr-3">
                  <span className="flex items-baseline gap-2">
                    <span className="font-mono text-[13px] tabular-nums text-print">
                      {String(e.seq).padStart(2, "0")}
                    </span>
                    <span className={`cardprint text-xs ${style.ink}`}>{style.long}</span>
                  </span>
                  <span className="line-clamp-2 text-[15px] font-semibold leading-snug text-ink">
                    {eventTitle(e)}
                  </span>
                  {meta && <span className="truncate font-mono text-[11px] text-ink-muted">{meta}</span>}
                </span>
                <PunchField source={punchSource(e)} className="mr-3 self-center" />
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

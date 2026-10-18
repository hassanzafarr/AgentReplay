// Hollerith card code, as punched on IBM 80-column cards. Each character is one column;
// a column's holes sit in the twelve rows, top to bottom: 12, 11, 0, 1 … 9.
//
// What a card punches is a digest of the event's input (hash plus prompt or tool args) *and*
// what was recorded for it (LLM output, tool result, clock reading, random value). Two events
// that took the same input and recorded the same answer punch identical cards; change either
// and the holes change, so a diverged card is visible as a different pattern.

import type { TraceEvent } from "./types";

export const ROWS = ["12", "11", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"] as const;

/** Row indexes (into ROWS) punched for one character. Unknown characters punch nothing. */
export function hollerith(ch: string): number[] {
  const c = ch.toUpperCase();
  const digit = (d: number) => ROWS.indexOf(String(d) as (typeof ROWS)[number]);
  if (c >= "0" && c <= "9") return [digit(Number(c))];
  const code = c.charCodeAt(0);
  if (c >= "A" && c <= "I") return [0, digit(code - 64)]; // zone 12 + 1..9
  if (c >= "J" && c <= "R") return [1, digit(code - 73)]; // zone 11 + 1..9
  if (c >= "S" && c <= "Z") return [2, digit(code - 81)]; // zone 0 + 2..9
  return [];
}

/** The characters a card punches: the first `columns` alphanumerics of the source text. */
export function punchText(source: string, columns: number): string {
  return source.replace(/[^0-9a-z]/gi, "").slice(0, columns).toUpperCase();
}

// FNV-1a, run twice with different offsets for 64 bits of spread. Not cryptographic; it only
// has to make different inputs punch visibly different cards, in the browser, with no deps.
function fnv32(text: string, seed: number): string {
  let h = seed >>> 0;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

// Input content is folded in alongside the stored hash, so a changed prompt or tool argument
// punches differently even in a hand-edited trace whose hash was never recomputed.
function recorded(e: TraceEvent): string {
  switch (e.event_type) {
    case "llm_call":
      return `${JSON.stringify(e.input_messages)}\u0000${e.output}`;
    case "tool_call":
      return `${JSON.stringify(e.input_args)}\u0000${e.error ?? e.output ?? ""}`;
    case "clock":
      return e.recorded_time;
    case "random":
      return e.value;
  }
}

/** The text a card punches for an event: 16 hex digits over its input hash and recorded answer. */
export function punchSource(e: TraceEvent): string {
  const key = `${e.hash || `${e.event_type}${e.seq}`}\u0000${recorded(e)}`;
  return fnv32(key, 0x811c9dc5) + fnv32(key, 0x2f6b4f11);
}

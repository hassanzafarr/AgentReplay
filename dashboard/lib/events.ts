import type { EventType } from "./types";

/* Event-type sort stripes. One table so the deck, the diff and the How it works page cannot
   drift apart. `stripe` is a fill; `ink` is the AA-safe text shade for use on card stock. */
export const EVENT_STYLES: Record<EventType, { stripe: string; ink: string; label: string; long: string }> = {
  llm_call: { stripe: "bg-ev-llm", ink: "text-ev-llm-ink", label: "LLM", long: "LLM call" },
  tool_call: { stripe: "bg-ev-tool", ink: "text-ev-tool-ink", label: "Tool", long: "Tool call" },
  clock: { stripe: "bg-ev-clock", ink: "text-ev-clock-ink", label: "Clock", long: "Clock read" },
  random: { stripe: "bg-ev-rng", ink: "text-ev-rng-ink", label: "RNG", long: "Random draw" },
};

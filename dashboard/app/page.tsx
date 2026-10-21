"use client";

import { useRef, useState } from "react";
import type { Trace, TraceEvent, EventType } from "@/lib/types";
import { parseTraceText, TraceFormatError } from "@/lib/validate";
import { EVENT_STYLES } from "@/lib/events";
import Timeline from "@/components/Timeline";
import EventDetail from "@/components/EventDetail";
import DiffView from "@/components/DiffView";
import ThemeToggle from "@/components/ThemeToggle";
import BrandMark from "@/components/BrandMark";
import PunchField from "@/components/PunchField";
import { CloseIcon, ExternalIcon, FileUpIcon, HelpIcon } from "@/components/Icons";
import Link from "next/link";

type Tab = "trace" | "diff";

async function fetchSample(name: string): Promise<Trace> {
  const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";
  const res = await fetch(`${basePath}/samples/${name}`);
  if (!res.ok) throw new Error(`sample ${name} not found`);
  return parseTraceText(await res.text());
}

/* ---------- drop zone: a blank card waiting to be punched ---------- */

function FileDropZone({
  label,
  onLoad,
}: {
  label: string;
  onLoad: (trace: Trace, name: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFile = (file: File) => {
    file.text().then(
      (text) => {
        let trace: Trace;
        try {
          trace = parseTraceText(text);
        } catch (err) {
          const reason = err instanceof TraceFormatError ? err.message : "It couldn't be read as a trace.";
          setError(`Couldn't load ${file.name}. ${reason}`);
          return;
        }
        setError(null);
        onLoad(trace, file.name);
      },
      () => setError(`Couldn't read ${file.name}. Try again or pick another file.`)
    );
  };

  return (
    <div className="flex flex-col gap-2">
      {/* A real button, so the picker opens from the keyboard as well as by click or drop. */}
      <button
        type="button"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files[0];
          if (file) handleFile(file);
        }}
        onClick={() => inputRef.current?.click()}
        data-lifted={dragging || undefined}
        className="deck-card group block w-full text-left"
      >
        <span className="punchcard flex items-stretch transition-colors group-hover:bg-card-2">
          <span aria-hidden className="w-2 shrink-0 bg-card-line" />
          <span className="flex flex-1 items-center gap-4 px-5 py-6">
            <FileUpIcon className="h-7 w-7 shrink-0 text-ink-muted" />
            <span className="flex min-w-0 flex-col gap-1">
              <span className="cardprint text-lg font-extrabold text-ink">{label}</span>
              <span className="text-sm text-ink-muted">Drop a .trace.json here, or click to browse</span>
            </span>
            <PunchField source="" className="ml-auto hidden sm:block" />
          </span>
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".json,application/json"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handleFile(f);
          e.target.value = ""; // allow re-picking the same file after a failed parse
        }}
      />
      {error && (
        <p role="alert" className="text-sm text-danger-desk">
          {error}
        </p>
      )}
    </div>
  );
}

/* ---------- deck header ---------- */

function DeckHeader({
  trace,
  name,
  onClear,
  compact = false,
}: {
  trace: Trace;
  name: string;
  onClear: () => void;
  compact?: boolean;
}) {
  const llm = trace.events.filter((e) => e.event_type === "llm_call").length;
  const tool = trace.events.filter((e) => e.event_type === "tool_call").length;
  return (
    <div className="flex items-start gap-3 border-b-2 border-on-desk pb-3">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <h2 className={`font-extrabold tracking-tight text-on-desk ${compact ? "text-xl" : "text-3xl"}`}>
          Deck <span className="font-mono font-normal">{trace.run_id.slice(0, 8)}</span>
        </h2>
        <p className="flex flex-wrap gap-x-4 gap-y-0.5 text-sm text-on-desk-muted">
          <span className="max-w-[18rem] truncate" title={name}>
            {name}
          </span>
          <span>
            <b className="text-on-desk">{trace.events.length}</b> cards · {llm} LLM · {tool} tool
          </span>
          <span>{new Date(trace.created_at).toLocaleString()}</span>
        </p>
      </div>
      <button
        type="button"
        onClick={onClear}
        aria-label={`Unload ${name}`}
        title="Unload deck"
        className="grid h-8 w-8 shrink-0 place-items-center text-on-desk-muted transition-colors hover:bg-desk-2 hover:text-on-desk"
      >
        <CloseIcon />
      </button>
    </div>
  );
}

/* ---------- event filter ---------- */

const FILTERS: EventType[] = ["llm_call", "tool_call", "clock", "random"];

function EventFilter({
  active,
  onToggle,
}: {
  active: Set<EventType>;
  onToggle: (k: EventType) => void;
}) {
  return (
    <div role="group" aria-label="Show event types" className="flex flex-wrap gap-1">
      {FILTERS.map((k) => {
        const on = active.has(k);
        return (
          <button
            key={k}
            type="button"
            aria-pressed={on}
            onClick={() => onToggle(k)}
            className={`cardprint flex min-h-7 items-center gap-1.5 border px-2 text-[11px] transition-colors ${
              on
                ? "border-card bg-card text-ink"
                : "border-desk-line text-on-desk-muted hover:text-on-desk"
            }`}
          >
            <span aria-hidden className={`h-2.5 w-2.5 ${EVENT_STYLES[k].stripe} ${on ? "" : "opacity-50"}`} />
            {EVENT_STYLES[k].label}
          </button>
        );
      })}
    </div>
  );
}

/* ---------- tabs ---------- */

const TABS: { key: Tab; label: string; short: string }[] = [
  { key: "trace", label: "Trace Viewer", short: "Trace" },
  { key: "diff", label: "Diff", short: "Diff" },
];

function Tabs({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  // Roving tabindex: Tab lands on the active tab, Left/Right switch between them.
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const next = TABS[(TABS.findIndex((t) => t.key === tab) + 1) % TABS.length].key;
    onChange(next);
    document.getElementById(`tab-${next}`)?.focus();
  };
  return (
    <div role="tablist" aria-label="View" onKeyDown={onKeyDown} className="ml-auto flex items-center gap-1">
      {TABS.map((t) => (
        <button
          key={t.key}
          id={`tab-${t.key}`}
          type="button"
          role="tab"
          aria-selected={tab === t.key}
          aria-controls={`panel-${t.key}`}
          tabIndex={tab === t.key ? 0 : -1}
          onClick={() => onChange(t.key)}
          className={`whitespace-nowrap px-3 py-1.5 text-sm font-semibold transition-colors ${
            tab === t.key ? "bg-card text-ink" : "text-on-desk-muted hover:text-on-desk"
          }`}
        >
          <span className="sm:hidden">{t.short}</span>
          <span className="hidden sm:inline">{t.label}</span>
        </button>
      ))}
    </div>
  );
}

/* ---------- page ---------- */

export default function Home() {
  const [tab, setTab] = useState<Tab>("trace");

  const [traceA, setTraceA] = useState<Trace | null>(null);
  const [traceAName, setTraceAName] = useState("");
  const [selectedEvent, setSelectedEvent] = useState<TraceEvent | null>(null);
  const [filter, setFilter] = useState<Set<EventType>>(new Set(FILTERS));

  const [diffA, setDiffA] = useState<Trace | null>(null);
  const [diffAName, setDiffAName] = useState("");
  const [diffB, setDiffB] = useState<Trace | null>(null);
  const [diffBName, setDiffBName] = useState("");

  const [sampleError, setSampleError] = useState<string | null>(null);

  const toggleFilter = (k: EventType) =>
    setFilter((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });

  const loadTraceSample = async () => {
    try {
      const t = await fetchSample("baseline.trace.json");
      setSampleError(null);
      setTraceA(t);
      setTraceAName("baseline.trace.json (sample)");
      setSelectedEvent(t.events.find((e) => e.event_type === "llm_call") ?? t.events[0] ?? null);
    } catch {
      setSampleError("Couldn't load the sample deck. Check your connection and try again.");
    }
  };

  const loadDiffSamples = async () => {
    try {
      const [a, b] = await Promise.all([
        fetchSample("baseline.trace.json"),
        fetchSample("candidate.trace.json"),
      ]);
      setSampleError(null);
      setDiffA(a);
      setDiffAName("baseline.trace.json (sample)");
      setDiffB(b);
      setDiffBName("candidate.trace.json (sample)");
    } catch {
      setSampleError("Couldn't load the sample decks. Check your connection and try again.");
    }
  };

  const shownEvents = traceA?.events.filter((e) => filter.has(e.event_type)) ?? [];

  const sampleErrorNote = sampleError && (
    <p role="alert" className="text-sm text-danger-desk">
      {sampleError}
    </p>
  );

  return (
    <div className="min-h-screen bg-desk">
      {/* Nav */}
      <header className="sticky top-0 z-20 border-b border-desk-line bg-desk">
        <div className="mx-auto flex max-w-7xl items-center gap-2 px-4 py-3 sm:gap-4 sm:px-6">
          <BrandMark />
          <Tabs tab={tab} onChange={setTab} />
          <Link
            href="/how-it-works"
            className="hidden text-sm font-medium text-on-desk-muted transition-colors hover:text-on-desk sm:block"
          >
            How it works
          </Link>
          <Link
            href="/how-it-works"
            aria-label="How it works"
            className="grid h-8 w-8 shrink-0 place-items-center text-on-desk-muted transition-colors hover:bg-desk-2 hover:text-on-desk sm:hidden"
          >
            <HelpIcon />
          </Link>
          <a
            href="https://github.com/hassanzafarr/AgentReplay"
            className="hidden items-center gap-1 text-sm font-medium text-on-desk-muted transition-colors hover:text-on-desk sm:flex"
            aria-label="GitHub (opens in a new tab)"
            target="_blank"
            rel="noopener noreferrer"
          >
            GitHub
            <ExternalIcon className="h-3.5 w-3.5" />
          </a>
          <ThemeToggle />
        </div>
      </header>

      <main>
        <h1 className="sr-only">AgentReplay trace viewer</h1>

        {/* Trace Viewer */}
        {tab === "trace" && (
          <div
            role="tabpanel"
            id="panel-trace"
            aria-labelledby="tab-trace"
            className="mx-auto flex max-w-7xl flex-col gap-6 p-4 sm:p-6"
          >
            {!traceA ? (
              <div className="mx-auto mt-10 flex w-full max-w-xl flex-col gap-4 sm:mt-16">
                <p className="text-balance text-2xl font-extrabold tracking-tight text-on-desk sm:text-3xl">
                  A recorded agent run is a deck of cards. Load one to read it card by card.
                </p>
                <FileDropZone
                  label="Load a deck"
                  onLoad={(t, n) => {
                    setTraceA(t);
                    setTraceAName(n);
                    setSelectedEvent(null);
                  }}
                />
                <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
                  <button
                    type="button"
                    onClick={loadTraceSample}
                    className="text-sm font-semibold text-on-desk underline decoration-desk-line underline-offset-4 hover:decoration-on-desk"
                  >
                    Try the sample deck →
                  </button>
                  <Link
                    href="/how-it-works"
                    className="text-sm text-on-desk-muted underline-offset-4 hover:text-on-desk hover:underline"
                  >
                    New here? See how AgentReplay works in 3 minutes
                  </Link>
                </div>
                {sampleErrorNote}
              </div>
            ) : (
              <>
                <DeckHeader
                  trace={traceA}
                  name={traceAName}
                  onClear={() => {
                    setTraceA(null);
                    setSelectedEvent(null);
                  }}
                />
                <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
                  {/* Deck */}
                  <div className="flex flex-col gap-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h2 className="cardprint text-xs text-on-desk-muted">
                        Deck · {shownEvents.length} of {traceA.events.length} cards
                      </h2>
                      <EventFilter active={filter} onToggle={toggleFilter} />
                    </div>
                    {/* Independent scroll only when the deck and listing sit side by side. */}
                    <div className="scroll-thin lg:max-h-[72vh] lg:overflow-y-auto">
                      <Timeline
                        events={shownEvents}
                        selectedSeq={selectedEvent?.seq}
                        onSelect={setSelectedEvent}
                      />
                    </div>
                  </div>
                  {/* Listing */}
                  <div className="flex flex-col gap-3">
                    <h2 className="sr-only">Listing for the selected card</h2>
                    <div className="scroll-thin lg:max-h-[72vh] lg:overflow-y-auto">
                      <EventDetail event={selectedEvent} />
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* Diff View */}
        {tab === "diff" && (
          <div
            role="tabpanel"
            id="panel-diff"
            aria-labelledby="tab-diff"
            className="mx-auto flex max-w-7xl flex-col gap-6 p-4 sm:p-6"
          >
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 sm:items-start">
              {diffA ? (
                <DeckHeader trace={diffA} name={diffAName} onClear={() => setDiffA(null)} compact />
              ) : (
                <FileDropZone
                  label="Deck A · baseline"
                  onLoad={(t, n) => {
                    setDiffA(t);
                    setDiffAName(n);
                  }}
                />
              )}
              {diffB ? (
                <DeckHeader trace={diffB} name={diffBName} onClear={() => setDiffB(null)} compact />
              ) : (
                <FileDropZone
                  label="Deck B · new version"
                  onLoad={(t, n) => {
                    setDiffB(t);
                    setDiffBName(n);
                  }}
                />
              )}
            </div>
            {!diffA && !diffB && (
              <button
                type="button"
                onClick={loadDiffSamples}
                className="self-start text-sm font-semibold text-on-desk underline decoration-desk-line underline-offset-4 hover:decoration-on-desk"
              >
                Or load the sample baseline and candidate →
              </button>
            )}
            {sampleErrorNote}
            <DiffView traceA={diffA} traceB={diffB} />
          </div>
        )}
      </main>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Trace, TraceEvent, EventType } from "@/lib/types";
import { resolveBlobs } from "@/lib/diff";
import Timeline from "@/components/Timeline";
import EventDetail from "@/components/EventDetail";
import DiffView from "@/components/DiffView";

type Tab = "trace" | "diff";

function parseTrace(text: string): Trace {
  const raw = JSON.parse(text);
  return resolveBlobs(raw as Trace);
}

async function fetchSample(name: string): Promise<Trace> {
  const res = await fetch(`/samples/${name}`);
  if (!res.ok) throw new Error(`sample ${name} not found`);
  return parseTrace(await res.text());
}

/* ---------- theme toggle ---------- */

function useTheme(): [boolean, () => void] {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);
  const toggle = useCallback(() => {
    setDark((d) => {
      const next = !d;
      document.documentElement.classList.toggle("dark", next);
      try {
        localStorage.setItem("ar-theme", next ? "dark" : "light");
      } catch {}
      return next;
    });
  }, []);
  return [dark, toggle];
}

function ThemeToggle() {
  const [dark, toggle] = useTheme();
  return (
    <button
      onClick={toggle}
      aria-label="Toggle theme"
      className="grid h-8 w-8 place-items-center rounded-lg border border-border text-fg-muted transition-colors hover:bg-surface-3 hover:text-fg"
    >
      {dark ? "☀️" : "🌙"}
    </button>
  );
}

/* ---------- file drop zone ---------- */

function FileDropZone({
  label,
  onLoad,
}: {
  label: string;
  onLoad: (trace: Trace, name: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleFile = (file: File) => {
    file.text().then((text) => {
      try {
        onLoad(parseTrace(text), file.name);
      } catch {
        alert(`Failed to parse ${file.name} — is it a valid .trace.json?`);
      }
    });
  };

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      onClick={() => inputRef.current?.click()}
      className={`flex cursor-pointer select-none flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed p-8 text-center transition-colors ${
        dragging
          ? "border-accent bg-accent/5"
          : "border-border-strong bg-surface-2 hover:border-accent/60"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".json"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handleFile(f);
        }}
      />
      <span className="text-2xl opacity-70">📂</span>
      <span className="text-sm font-medium text-fg">{label}</span>
      <span className="text-xs text-fg-subtle">Drop a .trace.json or click to browse</span>
    </div>
  );
}

/* ---------- trace header ---------- */

function TraceHeader({
  trace,
  name,
  onClear,
}: {
  trace: Trace;
  name: string;
  onClear: () => void;
}) {
  const llm = trace.events.filter((e) => e.event_type === "llm_call").length;
  const tool = trace.events.filter((e) => e.event_type === "tool_call").length;
  return (
    <div className="flex flex-1 flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-border bg-surface-2 px-4 py-2.5 text-xs">
      <span className="max-w-[16rem] truncate font-semibold text-fg" title={name}>
        {name}
      </span>
      <span className="font-mono text-fg-subtle">{trace.run_id.slice(0, 8)}…</span>
      <span className="text-fg-muted">
        <b className="text-fg">{trace.events.length}</b> events
      </span>
      <span className="text-fg-muted">
        {llm} LLM · {tool} tool
      </span>
      <span className="ml-auto text-fg-subtle">
        {new Date(trace.created_at).toLocaleString()}
      </span>
      <button
        onClick={onClear}
        className="rounded-md px-2 py-1 text-fg-subtle transition-colors hover:bg-surface-3 hover:text-fg"
      >
        ✕
      </button>
    </div>
  );
}

/* ---------- event filter ---------- */

const FILTERS: { key: EventType; label: string }[] = [
  { key: "llm_call", label: "LLM" },
  { key: "tool_call", label: "Tool" },
  { key: "clock", label: "Clock" },
  { key: "random", label: "RNG" },
];

function EventFilter({
  active,
  onToggle,
}: {
  active: Set<EventType>;
  onToggle: (k: EventType) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {FILTERS.map((f) => {
        const on = active.has(f.key);
        return (
          <button
            key={f.key}
            onClick={() => onToggle(f.key)}
            className={`rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset transition-colors ${
              on
                ? "bg-accent/15 text-accent ring-accent/30"
                : "text-fg-subtle ring-border hover:text-fg-muted"
            }`}
          >
            {f.label}
          </button>
        );
      })}
    </div>
  );
}

/* ---------- page ---------- */

export default function Home() {
  const [tab, setTab] = useState<Tab>("trace");

  const [traceA, setTraceA] = useState<Trace | null>(null);
  const [traceAName, setTraceAName] = useState("");
  const [selectedEvent, setSelectedEvent] = useState<TraceEvent | null>(null);
  const [filter, setFilter] = useState<Set<EventType>>(
    new Set(["llm_call", "tool_call", "clock", "random"])
  );

  const [diffA, setDiffA] = useState<Trace | null>(null);
  const [diffAName, setDiffAName] = useState("");
  const [diffB, setDiffB] = useState<Trace | null>(null);
  const [diffBName, setDiffBName] = useState("");

  const toggleFilter = (k: EventType) =>
    setFilter((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });

  const loadTraceSample = async () => {
    const t = await fetchSample("baseline.trace.json");
    setTraceA(t);
    setTraceAName("baseline.trace.json (sample)");
    setSelectedEvent(t.events.find((e) => e.event_type === "llm_call") ?? t.events[0] ?? null);
  };

  const loadDiffSamples = async () => {
    const [a, b] = await Promise.all([
      fetchSample("baseline.trace.json"),
      fetchSample("candidate.trace.json"),
    ]);
    setDiffA(a);
    setDiffAName("baseline.trace.json (sample)");
    setDiffB(b);
    setDiffBName("candidate.trace.json (sample)");
  };

  const shownEvents = traceA?.events.filter((e) => filter.has(e.event_type)) ?? [];

  return (
    <div className="app-bg min-h-screen">
      {/* Nav */}
      <header className="sticky top-0 z-20 border-b border-border bg-surface/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-6 py-3">
          <div className="flex items-center gap-2.5">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 text-sm text-white">
              ⏮
            </span>
            <span className="bg-gradient-to-r from-violet-500 to-indigo-500 bg-clip-text text-lg font-bold tracking-tight text-transparent">
              AgentReplay
            </span>
            <span className="hidden font-mono text-[11px] text-fg-subtle sm:inline">
              trace viewer
            </span>
          </div>

          <div className="ml-auto flex items-center gap-1 rounded-lg border border-border bg-surface-2 p-0.5">
            {(["trace", "diff"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  tab === t
                    ? "bg-accent text-accent-fg shadow-sm"
                    : "text-fg-muted hover:text-fg"
                }`}
              >
                {t === "trace" ? "Trace Viewer" : "Diff"}
              </button>
            ))}
          </div>
          <a
            href="https://github.com"
            className="hidden text-fg-subtle transition-colors hover:text-fg sm:block"
            aria-label="Repository"
            title="Repository"
          >
            ↗
          </a>
          <ThemeToggle />
        </div>
      </header>

      {/* Trace Viewer */}
      {tab === "trace" && (
        <div className="mx-auto flex max-w-7xl flex-col gap-4 p-6">
          {!traceA ? (
            <div className="mx-auto mt-16 flex w-full max-w-md flex-col gap-3">
              <FileDropZone
                label="Load a trace"
                onLoad={(t, n) => {
                  setTraceA(t);
                  setTraceAName(n);
                  setSelectedEvent(null);
                }}
              />
              <button
                onClick={loadTraceSample}
                className="mx-auto text-sm text-accent underline-offset-4 hover:underline"
              >
                or try a sample trace →
              </button>
            </div>
          ) : (
            <>
              <TraceHeader
                trace={traceA}
                name={traceAName}
                onClear={() => {
                  setTraceA(null);
                  setSelectedEvent(null);
                }}
              />
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
                {/* Timeline */}
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <h2 className="text-sm font-semibold text-fg">
                      Event Timeline
                      <span className="ml-1.5 font-normal text-fg-subtle">
                        ({shownEvents.length})
                      </span>
                    </h2>
                    <EventFilter active={filter} onToggle={toggleFilter} />
                  </div>
                  <div className="scroll-thin max-h-[72vh] overflow-y-auto rounded-2xl border border-border bg-surface p-2">
                    <Timeline
                      events={shownEvents}
                      selectedSeq={selectedEvent?.seq}
                      onSelect={setSelectedEvent}
                    />
                  </div>
                </div>
                {/* Detail */}
                <div className="flex flex-col gap-2">
                  <h2 className="text-sm font-semibold text-fg">Event Detail</h2>
                  <div className="scroll-thin max-h-[72vh] overflow-y-auto rounded-2xl border border-border bg-surface">
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
        <div className="mx-auto flex max-w-7xl flex-col gap-4 p-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {diffA ? (
              <TraceHeader trace={diffA} name={diffAName} onClear={() => setDiffA(null)} />
            ) : (
              <FileDropZone
                label="Trace A — baseline"
                onLoad={(t, n) => {
                  setDiffA(t);
                  setDiffAName(n);
                }}
              />
            )}
            {diffB ? (
              <TraceHeader trace={diffB} name={diffBName} onClear={() => setDiffB(null)} />
            ) : (
              <FileDropZone
                label="Trace B — new version"
                onLoad={(t, n) => {
                  setDiffB(t);
                  setDiffBName(n);
                }}
              />
            )}
          </div>
          {!diffA && !diffB && (
            <button
              onClick={loadDiffSamples}
              className="mx-auto text-sm text-accent underline-offset-4 hover:underline"
            >
              or load a sample baseline vs. candidate →
            </button>
          )}
          <div className="scroll-thin max-h-[70vh] overflow-y-auto rounded-2xl border border-border bg-surface">
            <DiffView traceA={diffA} traceB={diffB} />
          </div>
        </div>
      )}
    </div>
  );
}

"use client";

import { useCallback, useRef, useState } from "react";
import type { Trace, TraceEvent } from "@/lib/types";
import { resolveBlobs } from "@/lib/diff";
import Timeline from "@/components/Timeline";
import EventDetail from "@/components/EventDetail";
import DiffView from "@/components/DiffView";

type Tab = "trace" | "diff";

function parseTrace(text: string): Trace {
  const raw = JSON.parse(text);
  return resolveBlobs(raw as Trace);
}

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

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      onClick={() => inputRef.current?.click()}
      className={`
        flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed
        p-6 cursor-pointer transition-colors text-center select-none
        ${dragging ? "border-violet-400 bg-violet-50" : "border-gray-300 hover:border-violet-300 bg-gray-50"}
      `}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".json"
        className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
      />
      <span className="text-2xl">📂</span>
      <span className="text-sm font-medium text-gray-600">{label}</span>
      <span className="text-xs text-gray-400">Drop a .trace.json or click to browse</span>
    </div>
  );
}

function TraceHeader({ trace, name }: { trace: Trace; name: string }) {
  const llmCount = trace.events.filter((e) => e.event_type === "llm_call").length;
  const toolCount = trace.events.filter((e) => e.event_type === "tool_call").length;
  return (
    <div className="rounded-lg border bg-gray-50 px-4 py-3 text-xs font-mono text-gray-600 flex flex-wrap gap-4 flex-1 min-w-0">
      <span className="font-semibold text-gray-800 truncate">{name}</span>
      <span>run_id: {trace.run_id.slice(0, 8)}…</span>
      <span>{trace.events.length} events</span>
      <span>{llmCount} LLM · {toolCount} tool</span>
      <span>{new Date(trace.created_at).toLocaleString()}</span>
    </div>
  );
}

export default function Home() {
  const [tab, setTab] = useState<Tab>("trace");

  // Trace viewer state
  const [traceA, setTraceA] = useState<Trace | null>(null);
  const [traceAName, setTraceAName] = useState("");
  const [selectedEvent, setSelectedEvent] = useState<TraceEvent | null>(null);

  // Diff state
  const [diffA, setDiffA] = useState<Trace | null>(null);
  const [diffAName, setDiffAName] = useState("");
  const [diffB, setDiffB] = useState<Trace | null>(null);
  const [diffBName, setDiffBName] = useState("");

  return (
    <div className="min-h-screen bg-white font-sans">
      {/* Nav */}
      <header className="border-b px-6 py-3 flex items-center gap-4">
        <span className="font-bold text-gray-900 text-lg tracking-tight">AgentReplay</span>
        <span className="text-xs text-gray-400 font-mono">dashboard</span>
        <div className="ml-auto flex gap-1">
          {(["trace", "diff"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                tab === t
                  ? "bg-violet-600 text-white"
                  : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              {t === "trace" ? "Trace Viewer" : "Diff"}
            </button>
          ))}
        </div>
      </header>

      {/* Trace Viewer */}
      {tab === "trace" && (
        <div className="flex flex-col gap-4 p-6 max-w-7xl mx-auto">
          {!traceA ? (
            <div className="max-w-md mx-auto mt-16">
              <FileDropZone
                label="Load a trace"
                onLoad={(t, n) => { setTraceA(t); setTraceAName(n); setSelectedEvent(null); }}
              />
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <TraceHeader trace={traceA} name={traceAName} />
                <button
                  onClick={() => { setTraceA(null); setSelectedEvent(null); }}
                  className="shrink-0 rounded-md px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-100"
                >
                  ✕ Clear
                </button>
              </div>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {/* Timeline */}
                <div className="flex flex-col gap-2">
                  <h2 className="text-sm font-semibold text-gray-700">Event Timeline</h2>
                  <div className="rounded-xl border p-3 overflow-y-auto max-h-[70vh]">
                    <Timeline
                      events={traceA.events}
                      selectedSeq={selectedEvent?.seq}
                      onSelect={setSelectedEvent}
                    />
                  </div>
                </div>
                {/* Detail */}
                <div className="flex flex-col gap-2">
                  <h2 className="text-sm font-semibold text-gray-700">Event Detail</h2>
                  <div className="rounded-xl border overflow-y-auto max-h-[70vh]">
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
        <div className="flex flex-col gap-4 p-6 max-w-7xl mx-auto">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {diffA ? (
              <div className="flex items-center gap-2">
                <TraceHeader trace={diffA} name={diffAName} />
                <button
                  onClick={() => setDiffA(null)}
                  className="shrink-0 rounded-md px-2 py-1 text-sm text-gray-500 hover:bg-gray-100"
                >
                  ✕
                </button>
              </div>
            ) : (
              <FileDropZone
                label="Load Trace A (baseline)"
                onLoad={(t, n) => { setDiffA(t); setDiffAName(n); }}
              />
            )}
            {diffB ? (
              <div className="flex items-center gap-2">
                <TraceHeader trace={diffB} name={diffBName} />
                <button
                  onClick={() => setDiffB(null)}
                  className="shrink-0 rounded-md px-2 py-1 text-sm text-gray-500 hover:bg-gray-100"
                >
                  ✕
                </button>
              </div>
            ) : (
              <FileDropZone
                label="Load Trace B (new version)"
                onLoad={(t, n) => { setDiffB(t); setDiffBName(n); }}
              />
            )}
          </div>
          <div className="rounded-xl border overflow-y-auto max-h-[65vh]">
            <DiffView traceA={diffA} traceB={diffB} />
          </div>
        </div>
      )}
    </div>
  );
}

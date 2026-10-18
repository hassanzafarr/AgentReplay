// Turns untrusted JSON (a dropped file) into a Trace the UI can render without crashing.
// Mirrors the parts of agentreplay/schema/trace.py the dashboard relies on: required
// fields are checked, optional v2 fields pass through, and newer schema versions are
// rejected, just like the Python reader does, instead of being rendered half-understood.

import type { MessageRecord, Trace, TraceEvent } from "./types";

/** Highest schema_version this dashboard understands (agentreplay SCHEMA_VERSION). */
export const SUPPORTED_SCHEMA_VERSION = 2;

/** A file that parsed as JSON but is not a trace this dashboard can show. */
export class TraceFormatError extends Error {
  name = "TraceFormatError";
}

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isInt = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v);

function fail(msg: string): never {
  throw new TraceFormatError(msg);
}

function requireStr(o: Obj, key: string, where: string): string {
  const v = o[key];
  if (!isStr(v)) fail(`${where} is missing "${key}" (expected text).`);
  return v;
}

function optionalStrOrNull(o: Obj, key: string, where: string): string | null {
  const v = o[key];
  if (v === undefined || v === null) return null;
  if (!isStr(v)) fail(`${where} has a non-text "${key}".`);
  return v;
}

function validateMessages(v: unknown, where: string): MessageRecord[] {
  if (!Array.isArray(v)) fail(`${where} is missing "input_messages" (expected a list).`);
  return v.map((m, j) => {
    const at = `${where} message ${j}`;
    if (!isObj(m)) fail(`${at} is not an object.`);
    const content = m.content;
    if (!isStr(content)) fail(`${at} has no text "content".`);
    return {
      ...m,
      content,
      role: isStr(m.role) ? m.role : undefined,
      type: isStr(m.type) ? m.type : undefined,
    };
  });
}

function validateEvent(raw: unknown, i: number, blobs: Record<string, string>): TraceEvent {
  if (!isObj(raw)) fail(`events[${i}] is not an object.`);
  const type = raw.event_type;
  const where = `events[${i}]${isStr(type) ? ` (${type})` : ""}`;
  if (!isInt(raw.seq)) fail(`${where} is missing an integer "seq".`);

  // Fields every event carries; tolerate their absence rather than rejecting old files.
  const base = {
    ...raw,
    seq: raw.seq,
    hash: isStr(raw.hash) ? raw.hash : "",
    ts: isStr(raw.ts) ? raw.ts : "",
  };

  switch (type) {
    case "llm_call": {
      // Large outputs live in the content-addressed blobs map; inline them here.
      const key = raw.output_blob_key;
      const output = isStr(key) && isStr(blobs[key]) ? blobs[key] : raw.output;
      if (!isStr(output)) {
        fail(
          isStr(key)
            ? `${where} points at blob "${key}", which is not in "blobs".`
            : `${where} is missing "output" (expected text).`
        );
      }
      return {
        ...base,
        event_type: "llm_call",
        model_name: requireStr(raw, "model_name", where),
        input_messages: validateMessages(raw.input_messages, where),
        output,
        kwargs: isObj(raw.kwargs) ? (raw.kwargs as Record<string, string>) : {},
      } as TraceEvent;
    }
    case "tool_call": {
      if (raw.input_args !== undefined && !isObj(raw.input_args))
        fail(`${where} has "input_args" that is not an object.`);
      return {
        ...base,
        event_type: "tool_call",
        tool_name: requireStr(raw, "tool_name", where),
        input_args: (raw.input_args as Obj | undefined) ?? {},
        output: optionalStrOrNull(raw, "output", where),
        error: optionalStrOrNull(raw, "error", where),
      } as TraceEvent;
    }
    case "clock":
      return {
        ...base,
        event_type: "clock",
        recorded_time: requireStr(raw, "recorded_time", where),
      } as TraceEvent;
    case "random":
      return {
        ...base,
        event_type: "random",
        source: requireStr(raw, "source", where),
        value: requireStr(raw, "value", where),
      } as TraceEvent;
    default:
      return fail(
        `${where} has unknown event_type ${JSON.stringify(type)}. ` +
          `Expected llm_call, tool_call, clock or random.`
      );
  }
}

/** Validate parsed JSON as a trace. Throws TraceFormatError with a readable reason. */
export function validateTrace(raw: unknown): Trace {
  if (!isObj(raw)) fail("The file is JSON, but not a trace object.");

  const version = raw.schema_version ?? SUPPORTED_SCHEMA_VERSION;
  if (!isInt(version) || version < 1) fail(`"schema_version" must be a positive integer.`);
  if (version > SUPPORTED_SCHEMA_VERSION) {
    fail(
      `This trace uses schema_version ${version}, but this dashboard reads up to ` +
        `${SUPPORTED_SCHEMA_VERSION}. Update the dashboard to view it.`
    );
  }

  if (!Array.isArray(raw.events)) {
    fail(`No "events" list found. This doesn't look like an AgentReplay trace.`);
  }
  const runId = requireStr(raw, "run_id", "The trace");
  const createdAt = requireStr(raw, "created_at", "The trace");

  if (raw.blobs !== undefined && !isObj(raw.blobs)) fail(`"blobs" must be an object.`);
  const blobs = (raw.blobs ?? {}) as Record<string, string>;

  return {
    schema_version: version,
    run_id: runId,
    created_at: createdAt,
    events: raw.events.map((e, i) => validateEvent(e, i, blobs)),
    blobs,
    metadata: isObj(raw.metadata) ? raw.metadata : {},
  };
}

/** Parse file text into a Trace. Every failure surfaces as a TraceFormatError. */
export function parseTraceText(text: string): Trace {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    fail("The file isn't valid JSON.");
  }
  return validateTrace(raw);
}

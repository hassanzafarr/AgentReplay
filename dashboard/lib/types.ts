// TypeScript types mirroring agentreplay/schema/trace.py (schema_version=1)

export type EventType = "llm_call" | "tool_call" | "clock" | "random";

export interface MessageRecord {
  role: string;
  content: string;
}

export interface LLMCallEvent {
  event_type: "llm_call";
  seq: number;
  hash: string;
  ts: string;
  model_name: string;
  input_messages: MessageRecord[];
  output: string;
  output_blob_key?: string;
  kwargs: Record<string, string>;
}

export interface ToolCallEvent {
  event_type: "tool_call";
  seq: number;
  hash: string;
  ts: string;
  tool_name: string;
  input_args: Record<string, unknown>;
  output: string | null;
  error: string | null;
}

export interface ClockEvent {
  event_type: "clock";
  seq: number;
  hash: string;
  ts: string;
  recorded_time: string;
}

export interface RandomEvent {
  event_type: "random";
  seq: number;
  hash: string;
  ts: string;
  source: string;
  value: string;
}

export type TraceEvent = LLMCallEvent | ToolCallEvent | ClockEvent | RandomEvent;

export interface Trace {
  schema_version: number;
  run_id: string;
  created_at: string;
  events: TraceEvent[];
  blobs: Record<string, string>;
  metadata: Record<string, unknown>;
}

// Divergence types (mirrors divergence.py)

export interface StructuralDivergence {
  position: number;
  description: string;
  event_a: string | null;
  event_b: string | null;
}

export interface ToolDivergence {
  seq_a: number;
  seq_b: number;
  tool_name: string;
  description: string;
  args_diff: string;
}

export interface LLMDivergence {
  seq_a: number;
  seq_b: number;
  description: string;
  prompt_changed: boolean;
  output_changed: boolean;
  output_diff: string;
}

export interface DiffStats {
  total_events_a: number;
  total_events_b: number;
  structural: number;
  tool_call: number;
  llm_output: number;
}

export interface DivergenceReport {
  summary: string;
  is_identical: boolean;
  structural_divergences: StructuralDivergence[];
  tool_divergences: ToolDivergence[];
  llm_divergences: LLMDivergence[];
  stats: DiffStats;
}

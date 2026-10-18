# AgentReplay — Project Context (CLAUDE.md)

Deterministic record/replay + regression-testing harness for LangGraph agents.
Record every impure input during a run (LLM responses, tool results, clock, RNG),
then replay the exact sequence offline at ~$0 to reproduce failures and diff a new
prompt/model/code version against recorded traces.

Full spec: [AGENTREPLAY_PLAN.md](AGENTREPLAY_PLAN.md).

## Current status

- **Phase 0 (spike): DONE — GATE GREEN.** Core bet proven. See `spike/`.
- **Phase 1 (recorder): DONE — 50/50 tests pass.** See `agentreplay/` and `tests/`.
- **Phase 2 (replayer + divergence): DONE — 92/92 tests pass.**
- **Phase 3 (pytest plugin + CI): DONE — 100/100 tests pass.**
- **Phase 4 (dashboard + polish): DONE.**
- **Phase 5a (OTel/Langfuse export): DONE — 125/125 tests pass.**
- **Phase 5b (schema v2: latency, tokens, model id, node): DONE — 148/148 tests pass, verified in Langfuse Cloud.**

### What Phase 1 built (2026-06-27)
- `agentreplay/schema/trace.py` — Pydantic v2 models: 4 event types as discriminated
  union, top-level Trace with blob storage, schema_version=1.
- `agentreplay/recorder/interceptor.py` — `RecordingChatModel` (BaseChatModel wrapper)
  with hybrid hash+cursor matching, blob support, sync + async.
- `agentreplay/recorder/tool_wrapper.py` — wraps `StructuredTool.func` to capture
  ToolCallEvents (wraps at func level, not `_run`, to avoid langchain config kwarg).
- `agentreplay/recorder/clock.py` — `VirtualClock` context manager + `now()` drop-in.
- `agentreplay/recorder/rng.py` — `VirtualRNG` context manager + `random()`/`uuid4()` drop-ins.
- `agentreplay/recorder/trace_writer.py` — JSON serialization with Pydantic round-trip.
- `agentreplay/recorder/collector.py` — thread-safe `TraceCollector` with atomic seq counter.
- `agentreplay/integrations/langgraph.py` — `wrap(build_fn, model)` public API.
- `agentreplay/__init__.py` — re-exports: `wrap`, `now`, `random`, `uuid4`, `Trace`.
- 50 tests across 7 test files, all passing.

### What Phase 2 built (2026-06-28)
- `agentreplay/replayer/replay_engine.py` — `ReplayEngine` + `ReplayResult`: runs agent
  against recorded trace, produces replay trace + divergence report at zero LLM cost.
  Internal `_ReplayChatModel` serves LLM responses; `_wrap_tool_for_replay` serves tool
  outputs — both capture events to a new replay trace for diffing.
- `agentreplay/replayer/matcher.py` — `TraceMatcher`: standalone hybrid hash+cursor matcher
  extracted from Phase 1 interceptor, with `MatchStats` for hit/miss reporting.
- `agentreplay/replayer/divergence.py` — `diff_traces()`: 3-tier diff (structural →
  tool-call → LLM output). Clock/RNG events filtered out (always deterministic on replay).
  `DivergenceReport.format_report()` for human-readable CLI output.
- `agentreplay/cli.py` — `agentreplay diff <a> <b>` and `agentreplay show <trace>` commands.
- 42 new tests across 3 test files. 92/92 total.

### What Phase 3 built (2026-06-28)
- `agentreplay/integrations/pytest_plugin.py` — pytest11 plugin: collects `.trace.json`
  files as `TraceItem` tests. Pass = identical replay; fail = divergence report printed.
  Configured via `agentreplay_traces` + `agentreplay_agent` ini options. Auto-inserts
  rootpath into sys.path so user modules are importable.
- `agentreplay/cli.py` — `agentreplay diff <a> <b>` and `agentreplay show <trace>` CLI.
- `agentreplay/integrations/langgraph.py` — auto-stores `_agentreplay_input` in trace
  metadata so plugin can replay without extra config.
- `agentreplay/replayer/replay_engine.py` — auto-stubs tools from trace events when
  build_fn takes 2 params and no tools are provided.
- `examples/research_agent/` — dogfood demo agent with auto-recording conftest.
- `.github/workflows/regression.yml` — CI: unit tests + trace regression suite on PR.
- 8 new tests in test_pytest_plugin.py. 100/100 total.

### What the spike proved (2026-06-27)
- LangGraph LLM calls are cleanly interceptable via a `BaseChatModel` wrapper
  (no monkeypatch needed).
- A recorded run replays to a **byte-identical** final state.
- Replay made **zero live calls**, proven by wrapping a `TripwireModel` that
  raises if called — it never fired. Stronger proof than a key-based low-bill run.
- 4/4 gate tests pass: `cd spike && python -m pytest test_spike.py -v`.

### Environment constraints
- **No `ANTHROPIC_API_KEY`** in this env. Spike used a deterministic `StandInModel`
  in place of `ChatAnthropic`; interception boundary is identical, so results
  transfer to a real model unchanged. Real-API verification deferred until a key exists.
- Windows / PowerShell primary. Python 3.11.8.
- Installed: langgraph 1.2.6, langchain-core 1.4.8, langchain-anthropic 1.4.8,
  anthropic 0.112.0, pydantic 2.12.5, pytest 8.3.3, pytest-asyncio 1.3.0.
- Git repo: github.com/hassanzafarr/AgentReplay (master).

## Architecture decisions (and why)

- **D1 Interception = `BaseChatModel` wrapper (plan 1a), not monkeypatch.**
  Stable extension point, less code, transfers to any provider. Rejected monkeypatch:
  fragile, per-provider, can't see LangChain message normalization.
- **D2 Matching = hybrid: input-hash → ordered cursor → miss = divergence.**
  Hash handles changed code paths; cursor disambiguates repeated identical prompts
  (retry loops); a miss is a *reported feature*, not a crash. Rejected pure-order
  (breaks on parallel nodes) and pure-hash (can't handle repeats).
- **D3 Trace = single JSON/run: `{schema_version, run_id, created_at, events[], blobs{}}`.**
  Events typed (`llm_call`/`tool_call`/`clock`/`random`), each with global `seq`
  ordering index (handles async), `ts`, `hash`. Large blobs content-addressed in
  `blobs{}` to fight bloat. All Pydantic. **Versions are additive-only (user decision
  2026-10-18):** a new version may only add optional fields defaulting to None, so every
  older trace still loads and keeps its own `schema_version`. Readers reject versions newer
  than `SCHEMA_VERSION` (Pydantic would otherwise drop unknown fields silently). v1 → v2 added
  `start_ts`/`duration_ms`/`node` (LLM + tool) and `model_id`/`usage` (LLM).
- **D4 Divergence = tiered: structural (graph path) + tool-call (free) lead;
  semantic LLM-judge opt-in (costs tokens).** Rejected exact text diff (brittle).
- **D5 Clock/RNG = virtualize within run scope via context manager**, record each
  draw as an ordered event, replay in sequence. Rejected global import-time patch
  (pollutes host process).

## Conventions

- Typed everything with Pydantic v2; small focused modules; docstrings explain WHY.
- Clean separation: `recorder/` ⟂ `replayer/` ⟂ `integrations/`. Schema is the contract.
- Tests written per-phase, not at the end. Each test docstring states what it proves
  AND what it deliberately does not cover.
- Don't build dashboard/CI before the record/replay core works (plan order).

## Known limitations (v1 stance)
- LangGraph-only. No CrewAI / raw OpenAI loops.
- Replay assumes read-mostly tools; write side effects not sandboxed (future work).
- Final-message replay only; no token-stream replay.
- **Native LLM tool-calling is not recorded/replayed:** the interceptor stores only
  `AIMessage.content`, and replay returns `AIMessage(content=...)`, so `tool_calls` are lost.
  Agents that route on `tool_calls` (ToolNode / ReAct) diverge on replay. Tests call tools
  directly from nodes. Biggest gap for real-world agents — fix before importer (step 4).
- Node-name-based structural diff: refactors that rename nodes create diff noise.
- Calls that bypass `BaseChatModel` (raw SDK) aren't intercepted — surface as missing events.

## Target layout (plan §4)
`agentreplay/{recorder,replayer,schema,integrations}/`, `cli.py`, `dashboard/`,
`examples/research_agent/`, `.github/workflows/regression.yml`. `spike/` is throwaway.

## What Phase 4 built (2026-06-28)
- `dashboard/` — Next.js 16 + TypeScript + Tailwind dashboard (client-side only, no backend)
  - `lib/types.ts` — TypeScript types mirroring Python schema
  - `lib/diff.ts` — port of `divergence.py` to TypeScript (runs in-browser, zero API calls)
  - `components/Timeline.tsx` — colour-coded event list, click-to-select
  - `components/EventDetail.tsx` — full prompt/response/args panel
  - `components/DiffView.tsx` — structural + tool + LLM diff with inline unified-diff blocks
  - `app/page.tsx` — single-page app: file drag-drop, Trace Viewer tab, Diff tab
- `agentreplay/cli.py` — `agentreplay serve [--port N]` starts dashboard via npm run dev
- `README.md` — updated with full architecture, quick-start, all phases done, non-goals

## What Phase 5a built (2026-10-18) — OTel/Langfuse export (observability plan step 1/4)
- `agentreplay/integrations/otel.py` — `export_trace(trace, tracer_provider=, include_content=,
  environment=)` turns a Trace into OTel spans post-hoc (root `agentreplay.run` + `chat <model>` /
  `execute_tool <name>` children; clock/RNG → root span events). GenAI semconv + `langfuse.*` attrs.
  Content withheld unless opted in (PII). Start times inferred from previous event `ts`
  (schema v1 has no start time) → `agentreplay.timing.inferred=true`.
  `otlp_tracer_provider()`, `langfuse_otlp_config()` (env → endpoint + Basic auth),
  `ResultTrackingExporter` (OTel exporters log failures, don't raise → CLI exit code).
- `agentreplay export <trace|dir>... [--endpoint|--langfuse|--console] [--header K=V]
  [--include-content] [--environment NAME]`.
- OTel is optional extra `agentreplay[otel]`, imported lazily; core never needs it.
- 25 tests in `test_otel_export.py`. 125/125 total. Verified live against a local OTLP/HTTP sink.

## What Phase 5b built (2026-10-18) — schema v2 (observability plan step 2/4)
- `schema/trace.py` — `SCHEMA_VERSION=2`; `TokenUsage`; optional `start_ts`, `duration_ms`, `node`
  on LLM + tool events, `model_id` + `usage` on LLM events; validator rejects future versions.
- `recorder/context.py` — `CallTimer` (wall-clock start + `perf_counter` duration) and
  `current_node()` (run_manager metadata → LangChain `var_child_runnable_config` fallback; the
  fallback is what tools and sync-models-in-async-nodes need).
- `recorder/interceptor.py` — records timing, node, `model_id` (response_metadata → llm_output →
  inner model attr) and `usage` (from `usage_metadata`). `tool_wrapper.py` — timing + node, also
  on errors. `replay_engine.py` — replay events get node + timing but **no usage/model_id**
  (replay spends no tokens; exported replays must not look like cost).
- `integrations/otel.py` — measured timing when present (`timing.inferred=false`), one span per
  consecutive node run, `gen_ai.request/response.model`, `gen_ai.usage.input/output_tokens`;
  cache counts under `agentreplay.usage.*` (Langfuse sums all `gen_ai.usage.*` keys).
- `cli.py show` prints node / ms / model / tokens. Dashboard `types.ts` + `EventDetail.tsx` show them.
- Divergence diff unchanged: compares behaviour only, so metric differences never diverge.
- 23 new tests (`test_v2_capture.py`, v2 cases in `test_schema.py`, `test_otel_export.py`).
  148/148 total. 4 bundled v1 golden traces still replay clean.

### Verified against real Langfuse Cloud (EU, 2026-10-18)
- Keys live in `.env` at repo root (gitignored; template `.env.example`). Load in bash with
  `set -a; source <(tr -d '\r' < .env); set +a` — never print values.
- Exported tree renders correctly: chat → GENERATION, tool → TOOL, nodes/root → SPAN; model id
  and usage (input/output/total) mapped; cache tokens not double-counted; environment tag works.
- **Must send `x-langfuse-ingestion-version: 4`** (now in `langfuse_otlp_config`) or OTel data
  can lag up to 15 min.
- **Langfuse drops spans older than its retention window silently** (export returns success).
  → `export_trace(shift_to_now=True)` / `--shift-to-now`; CLI warns for traces > 7 days old.
- **Orgs created on/after 2026-09-16 get HTTP 410 on legacy `GET /api/public/traces*`.** Reads
  must use `GET /api/public/v2/observations` (requires `fromStartTime`/`toStartTime`, filter by
  `traceId`, `fields=core,basic,model,usage,metrics,io`). The step-4 importer must use this API.
- Cost shows None for made-up model ids; real Claude ids should price via Langfuse's model table
  (unverified — no ANTHROPIC_API_KEY).

## Next action
Observability plan steps remaining:
3. Divergence results → Langfuse scores from pytest plugin.
4. Langfuse trace → AgentReplay trace importer.
Other follow-ups: demo GIF, PyPI publish, CrewAI / raw OpenAI support.

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
- **Not a git repo yet.**

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
  `blobs{}` to fight bloat. All Pydantic. **schema_version frozen at 1; changes are breaking.**
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

## Next action
Project complete (v1). All 4 phases done. Possible follow-ups:
- Demo GIF / screenshots for README
- PyPI publish (`pip install agentreplay`)
- CrewAI / raw OpenAI support (Phase 5)

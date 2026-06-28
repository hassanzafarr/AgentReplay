# AgentReplay

**Deterministic record/replay and regression-testing harness for LangGraph agents.**

Record every LLM call, tool response, clock value, and RNG draw during a live run. Replay the exact sequence offline to reproduce failures, diff a new prompt/model against recorded traces, and run regression tests — all at **~$0 API cost**.

---

## The Problem

AI agents are non-deterministic. Every run can behave differently because of four "impure" inputs:

| Source | Example |
|--------|---------|
| **LLM responses** | Same prompt, different completion each time |
| **Tool/API results** | Search returns different data over time |
| **The clock** | `datetime.now()` changes every second |
| **Randomness** | `random()`, `uuid4()` |

This makes agents nearly impossible to **debug** ("why did it fail last Tuesday?"), **test** ("did my prompt change break anything?"), or **compare** ("is the new model better for this workflow?").

Setting `temperature=0` is not enough — tool results still change, clocks still tick, and UUIDs are still random.

---

## The Solution

AgentReplay intercepts and records all four impure inputs during a live run. On replay, it feeds the recorded values back in exact sequence. The agent becomes **perfectly reproducible**.

```python
import agentreplay

# Record a live run — one-time API cost
wrapped = agentreplay.wrap(build_my_agent, model=ChatAnthropic(...))
result = wrapped.invoke({"topic": "carbon capture"})
# → saves ./traces/<run_id>.trace.json

# Replay offline — zero API calls, $0 cost
from agentreplay.replayer.replay_engine import ReplayEngine

engine = ReplayEngine(recorded_trace=trace, build_fn=build_my_agent, model=TripwireModel())
result = engine.run({"topic": "carbon capture"})
print(result.divergence_report.format_report())
```

---

## Key Features

### Record
Wraps your LangGraph agent transparently. Every LLM call, tool invocation, `datetime.now()`, and `random()` is captured as a typed, ordered event in a JSON trace file. Large responses are content-addressed in a `blobs` dict to control file size.

### Replay at $0
Re-runs your agent against a recorded trace with zero live API calls. Hybrid matching (content hash → ordered cursor → miss = divergence) pairs each call with its recorded response. A `TripwireModel` wrapper can prove no live calls were made — it raises if invoked.

### Divergence Detection
Replay an old trace against new code, prompt, or model. Three-tier comparison — all free:

1. **Structural** — did the agent take the same path through the graph?
2. **Tool-call** — same tool name, same args, same output?
3. **LLM output** — same prompt, same response?

```
❌ 2 divergence(s) found.
── Structural (1) ──────────────────────────
  [3] Event type changed: tool_call → llm_call
      A: tool_call(seq=3, tool=search)
      B: llm_call(seq=3, prompt="Summarize...")

── LLM Outputs (1) ─────────────────────────
  [seq 5→5] output changed
      -The company was founded in 1998...
      +The company was founded in 2001...
```

### pytest Regression Suite
Each `.trace.json` file becomes a regression test. CI runs them on every PR — green/red check, zero API cost.

```toml
# pyproject.toml
[tool.pytest.ini_options]
agentreplay_traces = "traces/"
agentreplay_agent  = "myagent:build_agent"
```

```
$ pytest
PASSED  traces/run_a1b2.trace.json::run_a1b2
FAILED  traces/run_c3d4.trace.json::run_c3d4
  ❌ 1 divergence: agent skipped research step after prompt change.
```

### Visual Dashboard
Inspect traces and compare two runs side-by-side in a browser:

```bash
agentreplay serve        # opens http://localhost:3000
```

- **Trace Viewer** — event timeline (LLM calls, tool calls, clock, RNG) with click-to-inspect detail panel showing full prompts and responses
- **Diff View** — load two traces, see structural + tool + LLM divergences highlighted

---

## Architecture

```
agentreplay/
├── schema/
│   └── trace.py              # Pydantic v2 models — the record/replay contract
├── recorder/
│   ├── interceptor.py        # RecordingChatModel (BaseChatModel wrapper, not monkeypatch)
│   ├── tool_wrapper.py       # Instruments StructuredTool.func to capture I/O
│   ├── clock.py              # VirtualClock — drop-in for datetime.now()
│   ├── rng.py                # VirtualRNG — drop-in for random()/uuid4()
│   ├── collector.py          # Thread-safe event accumulator, atomic seq counter
│   └── trace_writer.py       # JSON serialization with Pydantic round-trip
├── replayer/
│   ├── replay_engine.py      # ReplayEngine — re-runs agent at zero API cost
│   ├── matcher.py            # TraceMatcher — hybrid hash+cursor event lookup
│   └── divergence.py        # diff_traces() — 3-tier structural comparison
├── integrations/
│   ├── langgraph.py          # wrap() — public record API for LangGraph
│   └── pytest_plugin.py      # pytest11 plugin — .trace.json files as tests
├── cli.py                    # agentreplay diff / show / serve
dashboard/                    # Next.js + React visual trace inspector
examples/
└── research_agent/           # Dogfood demo with auto-recording conftest
.github/workflows/
└── regression.yml            # CI: runs full trace regression suite on PRs
```

### Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| **LLM interception** | `BaseChatModel` wrapper | Stable extension point, any provider, survives upgrades. Rejected monkeypatch: fragile, per-provider. |
| **Call matching** | Hybrid: hash → cursor → miss | Hash handles changed code paths; cursor disambiguates retry loops; miss = reported divergence, not crash. |
| **Trace format** | Single JSON per run, Pydantic v2 | Typed discriminated union, `schema_version=1`, content-addressed blobs, global `seq` index for async ordering. |
| **Divergence** | Structural + tool-call (free), semantic opt-in | Real regressions hide in graph path and tool args. LLM-judge costs tokens — keep it opt-in. |
| **Clock/RNG** | Context-manager scoped | No global import-time patching — won't pollute the host process. |

---

## Installation

```bash
git clone https://github.com/hassanzafarr/AgentReplay.git
cd AgentReplay
pip install -e ".[dev]"
```

## Quick Start

```python
import agentreplay
from langchain_anthropic import ChatAnthropic

def build_my_agent(model):
    # ... your StateGraph setup ...
    return graph.compile()

model = ChatAnthropic(model="claude-sonnet-4-5")
wrapped = agentreplay.wrap(build_fn=build_my_agent, model=model)
result = wrapped.invoke({"topic": "quantum computing"})
```

### Virtual Clock & RNG

Use AgentReplay's drop-in replacements inside your agent for full determinism:

```python
import agentreplay

timestamp = agentreplay.now()     # instead of datetime.now()
value     = agentreplay.random()  # instead of random.random()
run_id    = agentreplay.uuid4()   # instead of uuid.uuid4()
```

These pass through to stdlib normally. Inside a `wrap()` context they record/replay automatically.

### CLI

```bash
agentreplay show traces/run_abc.trace.json      # inspect a trace
agentreplay diff traces/old.trace.json traces/new.trace.json  # compare two traces
agentreplay serve                                # open visual dashboard
```

---

## Running Tests

```bash
python -m pytest tests/ -v
# 100 passed in ~2s
```

---

## Project Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0 — Spike | Done | Proved LLM interception works via `BaseChatModel` wrapper |
| Phase 1 — Recorder | Done | Schema, interceptor, tools, clock, RNG, trace writer, `wrap()` API |
| Phase 2 — Replayer + Divergence | Done | `ReplayEngine`, `TraceMatcher`, `diff_traces()`, CLI |
| Phase 3 — pytest + CI | Done | pytest plugin, GitHub Actions regression suite, examples |
| Phase 4 — Dashboard | Done | Next.js visual trace inspector + diff view, `agentreplay serve` |

---

## Explicit Non-Goals (v1)

- **Framework-agnostic** — LangGraph-only. No CrewAI or raw OpenAI loops.
- **Distributed agents** — Single-process only.
- **Hosted SaaS** — Self-host only.
- **Token-stream replay** — Records the final message, not the token stream.
- **Write-tool sandboxing** — Replay assumes read-mostly tools. Write side effects not sandboxed.

---

## License

MIT

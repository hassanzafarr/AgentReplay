# 🔄 AgentReplay

**Deterministic record/replay and regression-testing harness for LangGraph agents.**

Record every LLM call, tool response, and clock/RNG value during a run, then replay the exact sequence to reproduce failures and diff a new prompt/model version against recorded production traces — at **~$0 API cost**.

---

## The Problem

AI agents are non-deterministic. Every run can behave differently because of four "impure" inputs:

| Source | Example |
|--------|---------|
| **LLM responses** | Same prompt, different completion |
| **Tool/API results** | Search returns different data over time |
| **The clock** | `datetime.now()` changes every second |
| **Randomness** | `random()`, `uuid4()` |

This makes agents nearly impossible to **debug** ("why did it fail last Tuesday?"), **test** ("did my prompt change break anything?"), or **compare** ("is Claude better than GPT-4 for this workflow?").

Setting `temperature=0` is not enough — tool results still change, clocks still tick, and UUIDs are still random.

## The Solution

AgentReplay intercepts and records all four impure inputs during a live run. On replay, it feeds the recorded values back in the exact order they were requested. The agent becomes **perfectly reproducible**.

```python
import agentreplay

# 🔴 Record a live run
wrapped = agentreplay.wrap(build_my_agent, model=ChatAnthropic(...), mode="record")
result = wrapped.invoke({"topic": "carbon capture"})
# → trace saved to ./traces/<run_id>.trace.json

# ▶️ Replay it offline — zero API calls, $0 cost
wrapped = agentreplay.wrap(build_my_agent, model=ChatAnthropic(...), mode="replay", trace=recorded_trace)
result = wrapped.invoke({"topic": "carbon capture"})
# → byte-identical output, proven by TripwireModel pattern
```

---

## Key Features

### 🎯 Record Mode
Wraps your LangGraph agent transparently. Every LLM call, tool invocation, `datetime.now()`, and `random()` is captured as a typed, ordered event in a JSON trace file.

### ⏪ Replay Mode  
Re-runs your agent against a recorded trace with **zero live API calls**. Uses hybrid matching (content hash → ordered cursor → miss = divergence) to pair each call with its recorded response.

### 🔍 Divergence Detection *(coming in Phase 2)*
Replay an old trace against new code/prompt/model. Get a clear report: *"Your prompt change caused 3 of 14 runs to skip the research step entirely."*

### 🧪 Regression Testing *(coming in Phase 3)*
Recorded traces become pytest regression tests. CI runs them on every PR — green/red check with zero API cost.

---

## Architecture

```
agentreplay/
├── schema/
│   └── trace.py           # Pydantic v2 models — the contract between recorder & replayer
├── recorder/
│   ├── interceptor.py     # RecordingChatModel — BaseChatModel wrapper (not monkeypatch)
│   ├── tool_wrapper.py    # Instruments tool functions to capture I/O
│   ├── clock.py           # Virtualized datetime.now() via context manager
│   ├── rng.py             # Virtualized random/uuid via context manager
│   ├── collector.py       # Thread-safe event accumulator with atomic seq counter
│   └── trace_writer.py    # Serializes trace → JSON with Pydantic validation
├── integrations/
│   └── langgraph.py       # wrap() — the public entry point
└── __init__.py             # Re-exports: wrap, now, random, uuid4, Trace
```

### Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| **LLM interception** | `BaseChatModel` wrapper | Stable extension point, works with any provider, survives library upgrades. Rejected monkeypatch (fragile, per-provider). |
| **Call matching** | Hybrid: hash → cursor → miss | Hash handles changed code paths; cursor disambiguates retry loops; a miss is a *reported divergence*, not a crash. |
| **Trace format** | Single JSON per run, Pydantic models | Typed events with `schema_version=1`, content-addressed blob storage for large payloads, global `seq` index for async safety. |
| **Clock/RNG** | Context-manager scoped | No global import-time patching — won't pollute the host process. |

---

## Installation

```bash
# From source (recommended during development)
git clone https://github.com/hassanzafarr/AgentReplay.git
cd AgentReplay
pip install -e ".[dev]"
```

## Quick Start

```python
import agentreplay
from langchain_anthropic import ChatAnthropic

# Your existing LangGraph agent builder
def build_my_agent(model):
    # ... your StateGraph setup ...
    return graph.compile()

# Wrap it for recording
model = ChatAnthropic(model="claude-sonnet-4-20250514")
wrapped = agentreplay.wrap(
    build_fn=build_my_agent,
    model=model,
    mode="record",
    trace_dir="./traces",
)

# Run normally — trace is captured automatically
result = wrapped.invoke({"topic": "quantum computing", "research": "", "brief": ""})
print(f"Trace saved: {wrapped.last_trace_path}")
```

### Virtual Clock & RNG

For full determinism, use AgentReplay's drop-in replacements in your agent code:

```python
import agentreplay

# Instead of datetime.now()
timestamp = agentreplay.now()

# Instead of random.random()
value = agentreplay.random()

# Instead of uuid.uuid4()
run_id = agentreplay.uuid4()
```

These pass through to the real stdlib functions normally, but when inside a `wrap()` context, they record/replay automatically.

---

## Running Tests

```bash
python -m pytest tests/ -v
```

```
50 passed in 1.85s
```

---

## Project Status

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 0 — Spike** | ✅ Done | Proved LLM interception works via BaseChatModel wrapper |
| **Phase 1 — Recorder** | ✅ Done | Schema, interceptor, tools, clock, RNG, trace writer, `wrap()` API |
| **Phase 2 — Replayer + Divergence** | 🔜 Next | Replay engine, divergence detector, CLI |
| **Phase 3 — pytest + CI** | ⬜ Planned | pytest plugin, GitHub Actions regression suite |
| **Phase 4 — Dashboard** | ⬜ Planned | Web UI for trace visualization and diff viewing |

---

## Explicit Non-Goals (v1)

Naming what we *won't* build is as important as what we will:

- **Framework-agnostic support** — LangGraph-only for v1. No CrewAI or raw OpenAI loops.
- **Distributed/multi-process agents** — Single-process only.
- **Hosted SaaS** — Self-host only. No cloud service.
- **Token-level streaming replay** — Records the final message, not the token stream.
- **Write-tool sandboxing** — Replay assumes read-mostly tools. Side effects (DB writes) are not sandboxed.

---

## How It Works (Technical)

Agents are non-deterministic because of a handful of impure inputs. If you intercept and record all of them during a real run, then on replay feed the recorded values back in the exact order they were requested, the agent becomes perfectly reproducible.

```
┌─────────────┐     record      ┌──────────────┐     write     ┌──────────┐
│  LangGraph  │ ──────────────→ │ TraceCollector│ ────────────→ │  .json   │
│    Agent    │                 │  (seq, hash) │              │  trace   │
└─────────────┘                 └──────────────┘              └──────────┘
       │                                                           │
       │ replay                                                    │ read
       │                                                           │
       ▼                                                           ▼
┌─────────────┐     lookup      ┌──────────────┐     match     ┌──────────┐
│  LangGraph  │ ──────────────→ │   Matcher    │ ←───────────── │  .json   │
│    Agent    │ ←────────────── │ (hash+cursor)│              │  trace   │
└─────────────┘  recorded resp  └──────────────┘              └──────────┘
```

The interception layer is the entire project. Everything else (diffing, dashboard, CI) is scaffolding around it.

---

## License

MIT

---

## Contributing

This project is in active development. Issues and PRs welcome.

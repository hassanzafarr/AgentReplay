# AgentReplay — Build Plan

> Deterministic record/replay and regression-testing harness for LangGraph agents.
> Record every LLM call, tool response, and clock/RNG value during a run, then replay
> the exact sequence to reproduce failures and diff a new prompt/model version against
> recorded production traces, at near-zero API cost.

---

## 1. The core bet (read this first)

Agents are non-deterministic because of a handful of "impure" inputs:

1. **LLM responses** (the big one, and the expensive one)
2. **Tool / API results** (search, DB, HTTP calls return different data over time)
3. **The clock** (`datetime.now()`, timeouts)
4. **Randomness** (`random`, `uuid`, sampling)

If you can intercept and record all four during a real run, then on replay feed the
recorded values back in the exact order they were requested, the agent becomes
perfectly reproducible. That interception+ordering layer is the entire project.
Everything else (diffing, dashboard, CI) is scaffolding around it.

**De-risk this before building anything else.** If you can't cleanly intercept LLM
calls in LangGraph/LangChain, nothing else matters. So Phase 0 is a throwaway spike
to prove it works, before you write a single line of "real" code.

---

## 2. What "done" looks like (scope boundaries)

**In scope (v1):**
- A Python library that wraps a LangGraph app to record runs to a trace file.
- A replay engine that re-runs the agent against a recorded trace with zero live LLM/tool calls.
- A divergence detector: replay an OLD trace against NEW code/prompt/model, report where behavior changed.
- A pytest plugin so recorded traces become regression tests in CI.
- A minimal web dashboard to view traces and diffs.
- A GitHub Actions example that runs the regression suite on every PR.

**Explicitly OUT of scope for v1 (say so in the README, it shows judgment):**
- Framework-agnostic support (CrewAI, raw OpenAI loops). LangGraph-only is fine for v1.
- Distributed / multi-process agents.
- A hosted SaaS. Self-host only.
- Streaming token-level replay (record the final message, not the token stream, at first).

Naming the non-goals is itself a recruiter signal. It reads as "this person scopes."

---

## 3. Key design decisions (decide these now, write them in the README later)

**Decision 1 — How to intercept LLM calls.**
LangChain has a callback system, but callbacks are for *observing*, not *substituting* a
response. For replay you must actually *return* the recorded response instead of calling
the API. Two viable approaches:
- (a) A custom `BaseChatModel` wrapper that delegates to the real model in record mode
  and returns recorded responses in replay mode. Cleanest, most explicit.
- (b) Monkeypatch at the client layer. Faster to prototype, uglier, more fragile.
Start with (b) in the Phase 0 spike to prove the concept fast, then build (a) properly.

**Decision 2 — How to match a replayed call to its recorded response.**
This is the subtle part. On replay, when the agent makes "an LLM call," which recorded
response do you hand back? Options, in increasing robustness:
- *Call ordering* (1st call -> 1st recorded response). Simple, breaks if code path changes.
- *Input hashing* (hash the prompt; look up the matching recorded response). More robust,
  but a tiny prompt change misses. This is the right default.
- *Hybrid*: hash first, fall back to order, and on a miss, mark it a divergence (which is
  often exactly what you WANT to detect). This is the smart v1 behavior.

**Decision 3 — Trace format.**
Use a single JSON file per run, with an ordered list of "events." Each event is typed:
`llm_call`, `tool_call`, `clock`, `random`. Store inputs, outputs, timestamps, and a hash.
Version the schema from day one (`"schema_version": 1`). Pydantic models for everything.

**Decision 4 — What counts as a "divergence."**
LLM output is text, so exact-match diffing is too brittle (a reworded-but-equivalent
answer would flag). Tiered comparison:
- *Structural*: did the agent take the same path through the graph? Same nodes, same order?
  (This is deterministic and the most valuable signal.)
- *Tool-call level*: did it call the same tools with the same arguments?
- *Semantic* (optional, costs tokens): use an LLM-as-judge to score whether the final
  output is equivalent. Make this opt-in since it reintroduces API cost.
Lead with structural + tool-call diffing. That's where the real regressions hide and it's free.

---

## 4. Architecture (target shape)

```
agentreplay/
  recorder/
    interceptor.py     # wraps LLM + tools, captures events in record mode
    clock.py           # virtualized time source
    rng.py             # virtualized randomness/uuid
    trace_writer.py    # serializes ordered events -> JSON
  replayer/
    replay_engine.py   # feeds recorded events back, no live calls
    matcher.py         # hash/order/hybrid matching of call -> recorded response
    divergence.py      # structural + tool-call + (opt) semantic diff
  schema/
    trace.py           # Pydantic models, schema_version
  integrations/
    langgraph.py       # the public wrap() API for a LangGraph app
    pytest_plugin.py   # turns traces into regression tests
  cli.py               # record / replay / diff commands
dashboard/             # Next.js + React, reads trace JSON, renders timeline + diffs
examples/
  research_agent/      # YOUR Research & Brief Generator, instrumented (dogfood demo)
.github/workflows/
  regression.yml       # runs the pytest regression suite on PRs
```

---

## 5. Phased plan

### Phase 0 — Spike (2-3 days). Prove the core bet. THROWAWAY CODE.
- Take your existing Research & Brief Generator.
- Monkeypatch the LLM call so that on a second run, it returns the responses captured
  on the first run, with NO API call.
- Success criterion: run the agent once live, then run it again fully offline and get
  byte-identical LLM inputs flowing through the graph.
- If this works, the project is viable. If it fights you, solve interception before
  going further. Do not build anything else until this is green.

### Phase 1 — Recorder (week 1-2). The foundation.
- Proper `BaseChatModel` wrapper (Decision 1a) for record/replay modes.
- Virtualize clock and RNG (record real values, replay them back).
- Tool interception (wrap tool functions to capture inputs/outputs).
- Pydantic trace schema with `schema_version`, typed events, hashes, timestamps.
- `trace_writer` -> clean JSON file per run.
- Public API: `app = agentreplay.wrap(my_langgraph_app)`.
- Deliverable: run any LangGraph agent, get a complete, well-structured trace file.

### Phase 2 — Replayer + divergence (week 2-3). The payoff.
- Replay engine: re-run the agent, intercept each impure call, return recorded value.
- Matcher with hybrid hash+order+miss-detection (Decision 2).
- Divergence detector: structural graph-path diff, then tool-call diff (Decision 4).
- CLI: `agentreplay record`, `agentreplay replay <trace>`, `agentreplay diff <trace>`.
- Deliverable: replay an old trace against changed code, get a clear "here's what changed"
  report, having spent $0 on the LLM.

### Phase 3 — pytest + CI (week 3-4). The "production" signal.
- pytest plugin: point it at a folder of recorded traces; each becomes a test that fails
  on structural/tool divergence.
- GitHub Actions workflow that runs the suite on every PR against your example agent.
- Deliverable: a green/red check on a PR that says "your prompt change broke 2 of 14
  recorded behaviors." THIS is the screenshot that goes in the README.

### Phase 4 — Dashboard + polish (week 4-6). The recruiter-facing layer.
- Next.js/React app that loads a trace JSON and renders: the graph path as a timeline,
  each LLM call's prompt/response, and a side-by-side diff view for two traces.
- Optional opt-in semantic (LLM-judge) equivalence scoring, clearly flagged as costing tokens.
- README with: architecture diagram, a 60-second demo GIF, the "why temperature=0 isn't
  enough" explainer, quantified claims ("replays at ~$0", "catches path regressions"),
  and the explicit non-goals list.
- Deliverable: a repo a recruiter understands in 10 seconds and a dev can run in 5 minutes.

---

## 6. The dogfard demo (do not skip)

Instrument your **own** Research & Brief Generator as `examples/research_agent`. Then in
the README, show a real scenario:
> "I changed the Critic's prompt. AgentReplay replayed 14 recorded production runs offline
> and caught that 3 of them now skip the research loop entirely. Zero API calls."

That single concrete story does more than any feature list. It also closes the loop on
your last project, which makes your GitHub read like a deliberate progression rather than
scattered experiments.

---

## 7. Hard parts to watch (where you'll actually get stuck)

1. **Call matching on a changed code path.** When the new code makes a call the old trace
   never recorded, decide deliberately: is that a divergence to report, or an error?
   (Report it. That's the feature.)
2. **Async.** LangGraph runs can be async; your interceptors must handle both sync and async
   without reordering events. Capture an ordering index per event.
3. **Nested / parallel nodes.** If two nodes run concurrently, call order isn't deterministic,
   so pure ordering breaks. This is exactly why hash-based matching is the default, not order.
4. **Tool side effects.** Recording a tool's *output* is easy; the tool also having *written
   to a DB* is not replayable. v1 stance: document that replay assumes read-mostly tools, and
   note write-tool sandboxing as future work. (Naming this limitation is a maturity signal.)
5. **Trace bloat.** Big prompts make big traces. Store large blobs once and reference by hash.

---

## 8. README claims to earn (quantify these as you go)

- "Replays full agent runs at ~$0 LLM cost." (measure it)
- "Catches graph-path and tool-call regressions before deploy." (show a failing CI run)
- "Reproduces a specific failed run deterministically from its trace." (show it)
Numbers and a demo GIF beat adjectives. Recruiters skim; the GIF is the hook.

---

## 9. Suggested 6-week timeline

| Week | Focus | Exit criterion |
|------|-------|----------------|
| 0 (2-3 days) | Spike | Offline re-run with recorded LLM responses works |
| 1 | Recorder core | Clean trace file from any LangGraph app |
| 2 | Replayer + matcher | Replay an old trace at $0 |
| 3 | Divergence + CLI | `diff` reports structural + tool changes |
| 4 | pytest + GitHub Actions | Red/green regression check on a PR |
| 5 | Dashboard | Visual trace + diff viewer |
| 6 | Polish + launch | README, GIF, Show HN / r/LLMDevs post |

---

## 10. First three concrete actions

1. Create the repo with the structure in section 4 (empty stubs + README skeleton + the
   non-goals list).
2. Copy your Research & Brief Generator into `examples/research_agent`.
3. Do the Phase 0 spike against it. Get one offline re-run working before anything else.

If the spike works, you have a real project. If it doesn't, you've spent 3 days instead of 3 weeks.

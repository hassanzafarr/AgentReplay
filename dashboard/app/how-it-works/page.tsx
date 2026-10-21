import type { Metadata } from "next";
import Link from "next/link";
import ThemeToggle from "@/components/ThemeToggle";
import BrandMark from "@/components/BrandMark";
import { ArrowRightIcon, CheckIcon, CrossIcon, ExternalIcon } from "@/components/Icons";
import PunchField from "@/components/PunchField";
import { punchSource } from "@/lib/punch";
import { validateTrace } from "@/lib/validate";
import baselineSample from "@/public/samples/baseline.trace.json";
import candidateSample from "@/public/samples/candidate.trace.json";

// Card 01 of the bundled pair, read at build time through the same validator the viewer uses,
// so this page punches exactly what the Diff tab punches.
const SAMPLE_CARD_A = validateTrace(baselineSample).events.find((e) => e.seq === 1)!;
const SAMPLE_CARD_B = validateTrace(candidateSample).events.find((e) => e.seq === 1)!;
import { EVENT_STYLES } from "@/lib/events";
import type { EventType } from "@/lib/types";

export const metadata: Metadata = {
  title: "How it works — AgentReplay",
  description:
    "How AgentReplay records every non-deterministic input of a LangGraph agent run and replays it offline at $0 to catch regressions.",
};

const SECTIONS = [
  { id: "problem", label: "The problem" },
  { id: "pipeline", label: "Pipeline" },
  { id: "trace", label: "Trace format" },
  { id: "matching", label: "Matching" },
  { id: "divergence", label: "Divergence" },
  { id: "proof", label: "Proof of $0" },
  { id: "use", label: "Use it" },
];

/* ---------- small building blocks ---------- */

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className="scroll-mt-24 border-t-2 border-on-desk py-16"
    >
      <h2 id={`${id}-title`} className="text-balance text-3xl font-extrabold tracking-tight text-on-desk sm:text-4xl">
        {title}
      </h2>
      <div className="mt-6 text-base leading-relaxed text-on-desk-muted">{children}</div>
    </section>
  );
}

/* Code prints as a line-printer listing on card stock, captioned like a card field.
   min-w-0: as a grid item its long lines must scroll inside the listing, not widen the page. */
function Code({ children, label }: { children: string; label?: string }) {
  return (
    <figure className="punchcard flex min-w-0 flex-col">
      {label && (
        <figcaption className="cardprint border-b border-card-line px-4 py-2 text-[11px] text-ink-muted">
          {label}
        </figcaption>
      )}
      <pre className="listing scroll-thin overflow-x-auto px-4 py-3 font-mono text-[13px]">{children}</pre>
    </figure>
  );
}

function Chip({ kind, children }: { kind: EventType; children: React.ReactNode }) {
  return (
    <span className="punchcard inline-flex items-center gap-2 py-1 pl-0 pr-3 font-mono text-[12px] text-ink">
      <span aria-hidden className={`h-5 w-1.5 ${EVENT_STYLES[kind].stripe}`} />
      {children}
    </span>
  );
}

const inline = "font-mono text-[0.92em] text-on-desk";

/* Table verdicts drawn, not typed: the icon carries the mark, the sr-only word carries meaning. */
function Yes() {
  return (
    <>
      <CheckIcon className="h-4 w-4 text-ev-llm-ink" />
      <span className="sr-only">Yes</span>
    </>
  );
}
function No({ children }: { children?: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <CrossIcon className="h-4 w-4 text-print" />
      {children ?? <span className="sr-only">No</span>}
    </span>
  );
}

/* ---------- page ---------- */

export default function HowItWorks() {
  return (
    <div className="min-h-screen bg-desk">
      <header className="sticky top-0 z-20 border-b border-desk-line bg-desk">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-3 sm:gap-4 sm:px-6">
          <Link href="/" aria-label="AgentReplay home">
            <BrandMark />
          </Link>
          <div className="ml-auto flex items-center gap-3">
            <Link
              href="/"
              className="whitespace-nowrap bg-card px-3 py-1.5 text-sm font-semibold text-ink transition-colors hover:bg-card-2"
            >
              Open trace viewer
            </Link>
            <a
              href="https://github.com/hassanzafarr/AgentReplay"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="GitHub (opens in a new tab)"
              className="hidden items-center gap-1 text-sm text-on-desk-muted transition-colors hover:text-on-desk sm:flex"
            >
              GitHub
              <ExternalIcon className="h-3.5 w-3.5" />
            </a>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 sm:px-6">
        {/* Hero */}
        <div className="animate-deal pb-14 pt-16 sm:pt-24">
          <h1 className="max-w-4xl text-balance text-5xl font-extrabold leading-[1.02] tracking-tight text-on-desk sm:text-7xl">
            Record an agent run once.{" "}
            <span className="block font-bold [font-stretch:72%]">Replay it forever, offline, at $0.</span>
          </h1>
          <p className="mt-6 max-w-[60ch] text-lg leading-relaxed text-on-desk-muted">
            AgentReplay works like a flight recorder for LangGraph agents. It captures every
            non-deterministic input during a real run, then feeds those inputs back so the agent
            behaves exactly the same way again. Any recorded run then works as a free regression
            test: change a prompt, a model or the code, and AgentReplay tells you exactly which
            step changed.
          </p>
          <nav aria-label="Sections" className="mt-10 flex flex-wrap gap-1.5">
            {SECTIONS.map((s) => (
              <a
                key={s.id}
                href={`#${s.id}`}
                className="cardprint border border-desk-line px-2.5 py-1 text-[11px] text-on-desk-muted transition-colors hover:border-on-desk hover:text-on-desk"
              >
                {s.label}
              </a>
            ))}
          </nav>
        </div>

        {/* 1. Problem */}
        <Section id="problem" title="Agents are non-deterministic programs">
          <p className="max-w-[60ch]">
            A normal function returns the same output for the same input. An agent doesn&apos;t,
            because its output depends on four inputs that change between runs. That makes
            failures hard to reproduce and changes hard to test, and every &ldquo;test run&rdquo;
            against the live API costs money.
          </p>
          <div className="mt-8 grid gap-2 sm:grid-cols-2">
            {[
              { k: "llm_call" as const, t: "LLM responses", d: "The same prompt can return a different completion. Even temperature=0 isn't guaranteed to be identical." },
              { k: "tool_call" as const, t: "Tool & API results", d: "A search or database call returns different data next week." },
              { k: "clock" as const, t: "The clock", d: "datetime.now() returns a new value on every call." },
              { k: "random" as const, t: "Randomness", d: "random(), uuid4() and sampled IDs are different every run." },
            ].map((c) => (
              <div key={c.t} className="punchcard flex">
                <span aria-hidden className={`w-2 shrink-0 ${EVENT_STYLES[c.k].stripe}`} />
                <div className="px-4 py-4">
                  <h3 className={`cardprint text-sm ${EVENT_STYLES[c.k].ink}`}>{c.t}</h3>
                  <p className="mt-1.5 text-sm text-ink">{c.d}</p>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-8 max-w-[60ch]">
            <b className="text-on-desk">The core idea:</b> if every impure input is recorded and replayed,
            the agent becomes deterministic, and deterministic programs can be tested.
          </p>
        </Section>

        {/* 2. Pipeline */}
        <Section id="pipeline" title="Record → Replay → Diff → Regress">
          <ol className="grid gap-x-8 gap-y-8 md:grid-cols-4">
            {[
              { n: "1", t: "Record", d: "Wrap your agent with one line. Every LLM call, tool call, clock read and random draw is saved as an ordered event in a trace file.", tag: "pays API cost once" },
              { n: "2", t: "Replay", d: "Rebuild the same agent with a replay model. Each call is answered from the trace, so nothing reaches the network.", tag: "$0 · milliseconds" },
              { n: "3", t: "Diff", d: "Compare what the agent did on replay with what it did when recorded: graph path, tool arguments and prompts.", tag: "3 tiers, all free" },
              { n: "4", t: "Regress", d: "A pytest plugin turns every .trace.json file into a test. CI runs them on each pull request without an API key.", tag: "green / red in CI" },
            ].map((s, i) => (
              <li key={s.n} className="relative border-t border-desk-line pt-4">
                <h3 className="text-xl font-extrabold text-on-desk">{s.t}</h3>
                <p className="mt-2 text-sm">{s.d}</p>
                <p className="cardprint mt-3 text-[11px] text-on-desk">{s.tag}</p>
                {i < 3 && (
                  <ArrowRightIcon className="absolute -right-6 top-5 hidden h-4 w-4 text-on-desk-muted md:block" />
                )}
              </li>
            ))}
          </ol>

          <div className="mt-12 grid gap-8 lg:grid-cols-2">
            <div>
              <h3 className="text-lg font-bold text-on-desk">How interception works</h3>
              <p className="mt-2 text-sm">
                Every LLM call in LangGraph goes through LangChain&apos;s{" "}
                <code className={inline}>BaseChatModel</code>{" "}interface. AgentReplay
                hands your graph a model that implements that interface. While recording, it calls
                the real model and logs the exchange. While replaying, it answers from the trace.
                Your agent code doesn&apos;t change, and no provider SDK is monkeypatched.
              </p>
            </div>
            <div>
              <h3 className="text-lg font-bold text-on-desk">Clock & randomness, scoped</h3>
              <p className="mt-2 text-sm">
                <code className={inline}>agentreplay.now()</code>,{" "}
                <code className={inline}>random()</code>{" "}and{" "}
                <code className={inline}>uuid4()</code>{" "}are drop-in replacements that
                only record or replay inside a run&apos;s context manager. Outside a run they behave
                like the standard library, and nothing is patched globally in your process.
              </p>
            </div>
          </div>
        </Section>

        {/* 3. Trace format */}
        <Section id="trace" title="One JSON file per run">
          <p className="max-w-[60ch]">
            A trace is an ordered list of typed events. Each event has a global{" "}
            <code className={inline}>seq</code>{" "}(its order, which matters for async graphs)
            and a <code className={inline}>hash</code>{" "}of its input, which replay uses for
            matching. The schema is a set of Pydantic v2 models with a versioned{" "}
            <code className={inline}>schema_version</code>. New versions only add optional
            fields (v2 adds latency, token usage, model id and graph node), so old traces keep validating.
            Large outputs are stored once in <code className={inline}>blobs</code>{" "}and
            referenced by content hash.
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            <Chip kind="clock">clock</Chip>
            <Chip kind="llm_call">llm_call</Chip>
            <Chip kind="tool_call">tool_call</Chip>
            <Chip kind="random">random</Chip>
          </div>
          <div className="mt-4">
            <Code label="baseline.trace.json (excerpt from the bundled sample)">{`{
  "schema_version": 1,
  "run_id": "a1b2c3d4-…",
  "events": [
    { "event_type": "clock",     "seq": 0, "recorded_time": "2026-07-09T14:22:03.120Z" },
    { "event_type": "llm_call",  "seq": 1, "hash": "11c22d33…",
      "model_name": "claude-sonnet-5",
      "input_messages": [{ "type": "human", "content": "Plan research for the topic: quantum error correction" }],
      "output": "I'll investigate the state of the art in quantum error correction…" },
    { "event_type": "tool_call", "seq": 2, "hash": "22d33e44…",
      "tool_name": "web_search",
      "input_args": { "query": "surface code error correction threshold 2026", "max_results": 5 },
      "output": "1. Google Quantum AI demonstrates below-threshold surface code …" },
    { "event_type": "random",    "seq": 3, "source": "uuid4", "value": "7f3c9a20-…" },
    { "event_type": "llm_call",  "seq": 4, "hash": "44f55667…", "output": "…" }
  ],
  "blobs": { }
}`}</Code>
          </div>
        </Section>

        {/* 4. Matching */}
        <Section id="matching" title="Which recorded answer goes with this call?">
          <p className="max-w-[60ch]">
            During replay, each call the agent makes has to be paired with the right recorded
            event. The two obvious approaches both fail on real agents, so AgentReplay combines
            them:
          </p>
          <ol className="mt-8 grid gap-x-8 gap-y-6 md:grid-cols-3">
            <li className="border-t border-desk-line pt-4">
              <h3 className="text-lg font-bold text-on-desk">Hash lookup</h3>
              <p className="mt-2 text-sm">
                Hash the call&apos;s input (messages or tool args) and look it up. Because the lookup
                uses content, not position, a matching call is found even if the code runs steps in
                a different order.
              </p>
            </li>
            <li className="border-t border-desk-line pt-4">
              <h3 className="text-lg font-bold text-on-desk">Ordered cursor</h3>
              <p className="mt-2 text-sm">
                If the same prompt appears more than once, as in a retry loop, a per-hash cursor
                returns the recordings in their original order: 1st, then 2nd, then 3rd.
              </p>
            </li>
            <li className="border-t-2 border-on-desk pt-4">
              <h3 className="text-lg font-bold text-on-desk">Miss = divergence</h3>
              <p className="mt-2 text-sm">
                No recording matches, so the new code made a call the original run never made.
                AgentReplay reports it, and that report is the regression signal. It is not treated
                as a crash.
              </p>
            </li>
          </ol>
          <div className="punchcard mt-8 overflow-x-auto">
            <table className="w-full min-w-[30rem] text-left text-sm text-ink">
              <thead className="cardprint border-b-2 border-ink text-[11px] text-ink-muted">
                <tr>
                  <th className="px-4 py-2.5 font-semibold">Strategy</th>
                  <th className="px-4 py-2.5 font-semibold">Reordered / parallel nodes</th>
                  <th className="px-4 py-2.5 font-semibold">Identical retries</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-card-line">
                <tr>
                  <td className="px-4 py-2.5">Order only</td>
                  <td className="px-4 py-2.5"><No>breaks</No></td>
                  <td className="px-4 py-2.5"><Yes /></td>
                </tr>
                <tr>
                  <td className="px-4 py-2.5">Hash only</td>
                  <td className="px-4 py-2.5"><Yes /></td>
                  <td className="px-4 py-2.5"><No>can&apos;t tell them apart</No></td>
                </tr>
                <tr className="bg-card-2 font-semibold">
                  <td className="px-4 py-2.5">Hash → cursor (AgentReplay)</td>
                  <td className="px-4 py-2.5"><Yes /></td>
                  <td className="px-4 py-2.5"><Yes /></td>
                </tr>
              </tbody>
            </table>
          </div>
        </Section>

        {/* 5. Divergence */}
        <Section id="divergence" title="Three tiers of “what changed?”">
          <p className="max-w-[60ch]">
            Comparing final outputs as exact text is brittle, and it hides where things went wrong.
            AgentReplay compares the two runs step by step, starting with the highest-signal checks:
          </p>
          <ol className="mt-6 flex flex-col">
            {[
              { n: "Structural", d: "Did the agent take the same path through the graph? A skipped or extra step is the clearest sign of a regression." },
              { n: "Tool calls", d: "Same tool, same arguments, same result? Changed arguments often show the root cause." },
              { n: "LLM calls", d: "Same prompt, same response? Shown as a unified diff, so a one-word prompt edit is easy to spot." },
            ].map((t, i) => (
              <li key={t.n} className="grid grid-cols-[3rem_1fr] gap-4 border-t border-desk-line py-4">
                <span className="font-mono text-lg text-on-desk">T{i + 1}</span>
                <div>
                  <h3 className="font-bold text-on-desk">{t.n}</h3>
                  <p className="mt-1 text-sm">{t.d}</p>
                </div>
              </li>
            ))}
          </ol>
          <p className="mt-4 max-w-[60ch] text-sm">
            All three tiers run locally and cost nothing. A semantic check (&ldquo;did the
            meaning change?&rdquo;) would need an LLM judge, which costs tokens, so it is left as an
            opt-in.
          </p>
          <div className="mt-6">
            <Code label="agentreplay diff baseline.trace.json candidate.trace.json · excerpt of the bundled pair">{`❌ 3 divergence(s) found.
   Trace A: 5 events
   Trace B: 5 events

── Tool Calls (1) ───────────────────────────
  [web_search] Tool 'web_search' called with different arguments
      -  "query": "surface code error correction threshold 2026",
      +  "query": "logical qubit overhead surface code 2026 fault tolerance",

── LLM Outputs (2) ──────────────────────────
  [seq 1→1] output changed
      -I'll investigate the state of the art in quantum error correction. …
      +I'll investigate quantum error correction, focusing on logical qubit overhead …
  [seq 4→4] output changed
      -Quantum error correction has crossed a milestone: …
      +Quantum error correction reached a turning point in 2025: …`}</Code>
          </div>
          {/* The thesis, punched with the same rule the deck uses, from the bundled sample pair. */}
          <figure className="mt-8">
            <div className="grid gap-2 md:grid-cols-3">
              {[
                { label: "Baseline · card 01", card: SAMPLE_CARD_A, note: "recorded" },
                { label: "Replayed · same input", card: SAMPLE_CARD_A, note: "same answer · same holes · match" },
                { label: "Candidate · card 01", card: SAMPLE_CARD_B, note: "new answer · new holes · diverges" },
              ].map((c, i) => (
                <div key={c.label} className="punchcard flex items-center gap-3 py-3 pl-5 pr-3">
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className={`cardprint text-xs ${i === 2 ? "text-print" : "text-ink-muted"}`}>{c.label}</span>
                    <span className="font-mono text-[11px] text-ink">
                      punched {punchSource(c.card).slice(0, 12).toUpperCase()}
                    </span>
                    <span className="text-xs text-ink-muted">{c.note}</span>
                  </div>
                  <PunchField source={punchSource(c.card)} />
                </div>
              ))}
            </div>
            <figcaption className="mt-2 max-w-[60ch] text-xs text-on-desk-muted">
              Card 01 of the bundled baseline and candidate traces, punched exactly as the deck and Diff
              views punch it: a digest of the call&apos;s input and its recorded answer, in Hollerith code.
              Same prompt, different answer, different card.
            </figcaption>
          </figure>
          <Link
            href="/"
            className="mt-5 inline-block text-sm font-semibold text-on-desk underline decoration-desk-line underline-offset-4 hover:decoration-on-desk"
          >
            Try it: open the Diff tab and load the sample baseline vs. candidate →
          </Link>
        </Section>

        {/* 6. Proof */}
        <Section id="proof" title="How do we know replay costs $0?">
          <div className="grid gap-8 lg:grid-cols-[1.1fr_1fr] lg:items-start">
            <div>
              <p>
                Saying &ldquo;the bill looked small&rdquo; doesn&apos;t prove anything. Instead,
                during replay the agent is built with a{" "}
                <b className="text-on-desk">TripwireModel</b>, a chat model that raises an exception the
                moment it is called.
              </p>
              <p className="mt-4">
                If replay ever fell through to a live model, the run would crash. It never does: the
                test suite, the CI regression job and the demo script all replay to the same final
                state as the recording, with the tripwire left untouched.
              </p>
              <ul className="mt-5 space-y-2 text-sm text-on-desk">
                {[
                  "148 unit + integration tests",
                  "Golden-trace regression suite on every push",
                  "Replay reproduces the recorded final state exactly",
                ].map((t) => (
                  <li key={t} className="flex items-center gap-2">
                    <CheckIcon className="h-4 w-4 shrink-0 text-ok-desk" />
                    {t}
                  </li>
                ))}
              </ul>
            </div>
            <Code label="the tripwire">{`class TripwireModel(BaseChatModel):
    def _generate(self, *args, **kwargs):
        raise RuntimeError("TRIPWIRE: live call!")

engine = ReplayEngine(
    recorded_trace=trace,
    build_fn=build_agent,
    model=TripwireModel(),   # never fires
)`}</Code>
          </div>
        </Section>

        {/* 7. Use */}
        <Section id="use" title="Three snippets">
          <div className="grid gap-3 lg:grid-cols-3">
            <Code label="1 · record">{`import agentreplay

wrapped = agentreplay.wrap(
    build_fn=build_my_agent,
    model=ChatAnthropic(...),
)
wrapped.invoke({"topic": "..."})
# → traces/<run_id>.trace.json`}</Code>
            <Code label="2 · test in CI">{`# pyproject.toml
[tool.pytest.ini_options]
agentreplay_traces = "traces/"
agentreplay_agent  = "app:build_agent"

$ pytest
traces/6eb6f580.trace.json PASSED`}</Code>
            <Code label="3 · inspect">{`agentreplay show run.trace.json
agentreplay diff old.json new.json
agentreplay serve   # this UI`}</Code>
          </div>

          <div className="punchcard mt-10 px-6 py-5">
            <h3 className="cardprint text-sm text-ink">Known limits (v1)</h3>
            <ul className="mt-3 grid gap-x-8 gap-y-1.5 text-sm text-ink sm:grid-cols-2">
              <li>· LangGraph only. CrewAI / raw OpenAI support is planned.</li>
              <li>· Replay assumes read-mostly tools. Writes aren&apos;t sandboxed.</li>
              <li>· Replays final messages, not token streams.</li>
              <li>· Renaming a graph node shows up as a structural diff.</li>
            </ul>
          </div>

          <div className="mt-10 flex flex-wrap items-center gap-3">
            <Link
              href="/"
              className="bg-card px-4 py-2 text-sm font-semibold text-ink transition-colors hover:bg-card-2"
            >
              Open the trace viewer →
            </Link>
            <a
              href="https://github.com/hassanzafarr/AgentReplay"
              target="_blank"
              rel="noopener noreferrer"
              className="border border-desk-line px-4 py-2 text-sm font-semibold text-on-desk transition-colors hover:border-on-desk"
            >
              View source on GitHub
            </a>
          </div>
        </Section>
      </main>

      <footer className="border-t border-desk-line py-8 text-center text-xs text-on-desk-muted">
        AgentReplay · MIT · built by Hassan Zafar
      </footer>
    </div>
  );
}

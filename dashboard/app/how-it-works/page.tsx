import type { Metadata } from "next";
import Link from "next/link";
import ThemeToggle from "@/components/ThemeToggle";

export const metadata: Metadata = {
  title: "How it works — AgentReplay",
  description:
    "How AgentReplay records every non-deterministic input of a LangGraph agent run and replays it offline at $0 to catch regressions.",
};

/* Event colours match the Trace Viewer timeline so the two pages read as one system. */
const EVENT = {
  llm: { dot: "bg-violet-500", text: "text-violet-600 dark:text-violet-300", chip: "bg-violet-500/10 ring-violet-500/25" },
  tool: { dot: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-300", chip: "bg-emerald-500/10 ring-emerald-500/25" },
  clock: { dot: "bg-sky-500", text: "text-sky-600 dark:text-sky-300", chip: "bg-sky-500/10 ring-sky-500/25" },
  rng: { dot: "bg-amber-500", text: "text-amber-600 dark:text-amber-300", chip: "bg-amber-500/10 ring-amber-500/25" },
} as const;

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

function Section({
  id,
  eyebrow,
  title,
  children,
}: {
  id: string;
  eyebrow: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24 border-t border-border py-16 first:border-t-0">
      <p className="font-mono text-xs uppercase tracking-widest text-accent">{eyebrow}</p>
      <h2 className="mt-2 text-2xl font-bold tracking-tight text-fg sm:text-3xl">{title}</h2>
      <div className="mt-6 text-[15px] leading-relaxed text-fg-muted">{children}</div>
    </section>
  );
}

function Code({ children, label }: { children: string; label?: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-code-bg">
      {label && (
        <div className="border-b border-white/10 px-4 py-2 font-mono text-[11px] text-slate-400">
          {label}
        </div>
      )}
      <pre className="scroll-thin overflow-x-auto p-4 font-mono text-[13px] leading-relaxed text-code-fg">
        {children}
      </pre>
    </div>
  );
}

function Pill({ kind, children }: { kind: keyof typeof EVENT; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 font-mono text-[12px] ring-1 ring-inset ${EVENT[kind].chip} ${EVENT[kind].text}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${EVENT[kind].dot}`} />
      {children}
    </span>
  );
}

/* ---------- page ---------- */

export default function HowItWorks() {
  return (
    <div className="app-bg min-h-screen">
      <header className="sticky top-0 z-20 border-b border-border bg-surface/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-5xl items-center gap-4 px-6 py-3">
          <Link href="/" className="flex items-center gap-2.5">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 text-sm text-white">
              ⏮
            </span>
            <span className="bg-gradient-to-r from-violet-500 to-indigo-500 bg-clip-text text-lg font-bold tracking-tight text-transparent">
              AgentReplay
            </span>
          </Link>
          <div className="ml-auto flex items-center gap-3">
            <Link
              href="/"
              className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg shadow-sm transition-opacity hover:opacity-90"
            >
              Open trace viewer
            </Link>
            <a
              href="https://github.com/hassanzafarr/AgentReplay"
              target="_blank"
              rel="noopener noreferrer"
              className="hidden text-sm text-fg-muted transition-colors hover:text-fg sm:block"
            >
              GitHub ↗
            </a>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6">
        {/* Hero */}
        <div className="animate-fade-in pb-10 pt-16 sm:pt-24">
          <p className="font-mono text-xs uppercase tracking-widest text-accent">How it works</p>
          <h1 className="mt-3 max-w-3xl text-4xl font-bold tracking-tight text-fg sm:text-5xl">
            Record an agent run once.{" "}
            <span className="bg-gradient-to-r from-violet-500 to-indigo-500 bg-clip-text text-transparent">
              Replay it forever, offline, at $0.
            </span>
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-fg-muted">
            AgentReplay works like a flight recorder for LangGraph agents. It captures every
            non-deterministic input during a real run, then feeds those inputs back so the agent
            behaves exactly the same way again. Any recorded run then works as a free regression
            test: change a prompt, a model or the code, and AgentReplay tells you exactly which
            step changed.
          </p>
          <nav className="mt-8 flex flex-wrap gap-2">
            {SECTIONS.map((s) => (
              <a
                key={s.id}
                href={`#${s.id}`}
                className="rounded-full border border-border bg-surface-2 px-3 py-1 text-xs font-medium text-fg-muted transition-colors hover:border-accent/50 hover:text-fg"
              >
                {s.label}
              </a>
            ))}
          </nav>
        </div>

        {/* 1. Problem */}
        <Section id="problem" eyebrow="01 · The problem" title="Agents are non-deterministic programs">
          <p className="max-w-3xl">
            A normal function returns the same output for the same input. An agent doesn&apos;t,
            because its output depends on four inputs that change between runs. That makes
            failures hard to reproduce and changes hard to test, and every &ldquo;test run&rdquo;
            against the live API costs money.
          </p>
          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            {[
              { k: "llm" as const, t: "LLM responses", d: "The same prompt can return a different completion. Even temperature=0 isn't guaranteed to be identical." },
              { k: "tool" as const, t: "Tool & API results", d: "A search or database call returns different data next week." },
              { k: "clock" as const, t: "The clock", d: "datetime.now() returns a new value on every call." },
              { k: "rng" as const, t: "Randomness", d: "random(), uuid4() and sampled IDs are different every run." },
            ].map((c) => (
              <div key={c.t} className="rounded-2xl border border-border bg-surface p-5">
                <div className="flex items-center gap-2">
                  <span className={`h-2.5 w-2.5 rounded-full ${EVENT[c.k].dot}`} />
                  <h3 className="font-semibold text-fg">{c.t}</h3>
                </div>
                <p className="mt-2 text-sm">{c.d}</p>
              </div>
            ))}
          </div>
          <p className="mt-6 max-w-3xl">
            <b className="text-fg">The core idea:</b> if every impure input is recorded and replayed,
            the agent becomes deterministic, and deterministic programs can be tested.
          </p>
        </Section>

        {/* 2. Pipeline */}
        <Section id="pipeline" eyebrow="02 · Pipeline" title="Record → Replay → Diff → Regress">
          <ol className="grid gap-3 md:grid-cols-4">
            {[
              {
                n: "1",
                t: "Record",
                d: "Wrap your agent with one line. Every LLM call, tool call, clock read and random draw is saved as an ordered event in a trace file.",
                tag: "pays API cost once",
              },
              {
                n: "2",
                t: "Replay",
                d: "Rebuild the same agent with a replay model. Each call is answered from the trace, so nothing reaches the network.",
                tag: "$0 · milliseconds",
              },
              {
                n: "3",
                t: "Diff",
                d: "Compare what the agent did on replay with what it did when recorded: graph path, tool arguments and prompts.",
                tag: "3 tiers, all free",
              },
              {
                n: "4",
                t: "Regress",
                d: "A pytest plugin turns every .trace.json file into a test. CI runs them on each pull request without an API key.",
                tag: "green / red in CI",
              },
            ].map((s, i) => (
              <li key={s.n} className="relative rounded-2xl border border-border bg-surface p-5">
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent/10 font-mono text-sm font-bold text-accent">
                  {s.n}
                </span>
                <h3 className="mt-3 font-semibold text-fg">{s.t}</h3>
                <p className="mt-1.5 text-sm">{s.d}</p>
                <p className="mt-3 font-mono text-[11px] text-fg-subtle">{s.tag}</p>
                {i < 3 && (
                  <span
                    aria-hidden
                    className="absolute -right-2.5 top-1/2 z-10 hidden h-5 w-5 -translate-y-1/2 place-items-center rounded-full border border-border bg-surface-2 text-[11px] text-fg-subtle md:grid"
                  >
                    →
                  </span>
                )}
              </li>
            ))}
          </ol>

          <div className="mt-8 grid gap-4 lg:grid-cols-2">
            <div className="rounded-2xl border border-border bg-surface p-5">
              <h3 className="font-semibold text-fg">How interception works</h3>
              <p className="mt-2 text-sm">
                Every LLM call in LangGraph goes through LangChain&apos;s{" "}
                <code className="font-mono text-fg">BaseChatModel</code>{" "}interface. AgentReplay
                hands your graph a model that implements that interface. While recording, it calls
                the real model and logs the exchange. While replaying, it answers from the trace.
                Your agent code doesn&apos;t change, and no provider SDK is monkeypatched.
              </p>
            </div>
            <div className="rounded-2xl border border-border bg-surface p-5">
              <h3 className="font-semibold text-fg">Clock & randomness, scoped</h3>
              <p className="mt-2 text-sm">
                <code className="font-mono text-fg">agentreplay.now()</code>,{" "}
                <code className="font-mono text-fg">random()</code>{" "}and{" "}
                <code className="font-mono text-fg">uuid4()</code>{" "}are drop-in replacements that
                only record or replay inside a run&apos;s context manager. Outside a run they behave
                like the standard library, and nothing is patched globally in your process.
              </p>
            </div>
          </div>
        </Section>

        {/* 3. Trace format */}
        <Section id="trace" eyebrow="03 · Trace format" title="One JSON file per run">
          <p className="max-w-3xl">
            A trace is an ordered list of typed events. Each event has a global{" "}
            <code className="font-mono text-fg">seq</code>{" "}(its order, which matters for async graphs)
            and a <code className="font-mono text-fg">hash</code>{" "}of its input, which replay uses for
            matching. The schema is a set of Pydantic v2 models with a frozen{" "}
            <code className="font-mono text-fg">schema_version</code>, so old traces keep validating.
            Large outputs are stored once in <code className="font-mono text-fg">blobs</code>{" "}and
            referenced by content hash.
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            <Pill kind="clock">clock</Pill>
            <Pill kind="llm">llm_call</Pill>
            <Pill kind="tool">tool_call</Pill>
            <Pill kind="rng">random</Pill>
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
        <Section id="matching" eyebrow="04 · Matching" title="Which recorded answer goes with this call?">
          <p className="max-w-3xl">
            During replay, each call the agent makes has to be paired with the right recorded
            event. The two obvious approaches both fail on real agents, so AgentReplay combines
            them:
          </p>
          <div className="mt-6 grid gap-3 md:grid-cols-3">
            <div className="rounded-2xl border border-border bg-surface p-5">
              <p className="font-mono text-xs text-fg-subtle">step 1</p>
              <h3 className="mt-1 font-semibold text-fg">Hash lookup</h3>
              <p className="mt-2 text-sm">
                Hash the call&apos;s input (messages or tool args) and look it up. Because the lookup
                uses content, not position, a matching call is found even if the code runs steps in
                a different order.
              </p>
            </div>
            <div className="rounded-2xl border border-border bg-surface p-5">
              <p className="font-mono text-xs text-fg-subtle">step 2</p>
              <h3 className="mt-1 font-semibold text-fg">Ordered cursor</h3>
              <p className="mt-2 text-sm">
                If the same prompt appears more than once, as in a retry loop, a per-hash cursor
                returns the recordings in their original order: 1st, then 2nd, then 3rd.
              </p>
            </div>
            <div className="rounded-2xl border border-accent/40 bg-accent/5 p-5">
              <p className="font-mono text-xs text-accent">step 3</p>
              <h3 className="mt-1 font-semibold text-fg">Miss = divergence</h3>
              <p className="mt-2 text-sm">
                No recording matches, so the new code made a call the original run never made.
                AgentReplay reports it, and that report is the regression signal. It is not treated
                as a crash.
              </p>
            </div>
          </div>
          <div className="mt-6 overflow-hidden rounded-2xl border border-border">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-2 text-xs uppercase tracking-wide text-fg-subtle">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Strategy</th>
                  <th className="px-4 py-2.5 font-medium">Reordered / parallel nodes</th>
                  <th className="px-4 py-2.5 font-medium">Identical retries</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border bg-surface">
                <tr>
                  <td className="px-4 py-2.5 text-fg">Order only</td>
                  <td className="px-4 py-2.5">✗ breaks</td>
                  <td className="px-4 py-2.5">✓</td>
                </tr>
                <tr>
                  <td className="px-4 py-2.5 text-fg">Hash only</td>
                  <td className="px-4 py-2.5">✓</td>
                  <td className="px-4 py-2.5">✗ can&apos;t tell them apart</td>
                </tr>
                <tr className="bg-accent/5">
                  <td className="px-4 py-2.5 font-semibold text-fg">Hash → cursor (AgentReplay)</td>
                  <td className="px-4 py-2.5">✓</td>
                  <td className="px-4 py-2.5">✓</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Section>

        {/* 5. Divergence */}
        <Section id="divergence" eyebrow="05 · Divergence" title="Three tiers of “what changed?”">
          <p className="max-w-3xl">
            Comparing final outputs as exact text is brittle, and it hides where things went wrong.
            AgentReplay compares the two runs step by step, starting with the highest-signal checks:
          </p>
          <div className="mt-6 space-y-3">
            {[
              { n: "Structural", d: "Did the agent take the same path through the graph? A skipped or extra step is the clearest sign of a regression." },
              { n: "Tool calls", d: "Same tool, same arguments, same result? Changed arguments often show the root cause." },
              { n: "LLM calls", d: "Same prompt, same response? Shown as a unified diff, so a one-word prompt edit is easy to spot." },
            ].map((t, i) => (
              <div key={t.n} className="flex gap-4 rounded-2xl border border-border bg-surface p-5">
                <span className="font-mono text-sm font-bold text-accent">T{i + 1}</span>
                <div>
                  <h3 className="font-semibold text-fg">{t.n}</h3>
                  <p className="mt-1 text-sm">{t.d}</p>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-6 max-w-3xl text-sm">
            All three tiers run locally and cost nothing. A semantic check (&ldquo;did the
            meaning change?&rdquo;) would need an LLM judge, which costs tokens, so it is left as an
            opt-in.
          </p>
          <div className="mt-4">
            <Code label="agentreplay diff baseline.trace.json candidate.trace.json">{`❌ 2 divergence(s) found.

── LLM Outputs (2) ──────────────────────────
  [seq 0→0] prompt changed, output changed
      -[Recorded response for: Research this topic thoroughly: carbon capture …]
      +[Recorded response for: Research this topic briefly: carbon capture …]
  [seq 1→1] prompt changed`}</Code>
          </div>
          <Link
            href="/"
            className="mt-4 inline-block text-sm text-accent underline-offset-4 hover:underline"
          >
            Try it: open the Diff tab and load the sample baseline vs. candidate →
          </Link>
        </Section>

        {/* 6. Proof */}
        <Section id="proof" eyebrow="06 · Proof" title="How do we know replay costs $0?">
          <div className="grid gap-6 lg:grid-cols-[1.1fr_1fr] lg:items-start">
            <div>
              <p>
                Saying &ldquo;the bill looked small&rdquo; doesn&apos;t prove anything. Instead,
                during replay the agent is built with a{" "}
                <b className="text-fg">TripwireModel</b>, a chat model that raises an exception the
                moment it is called.
              </p>
              <p className="mt-4">
                If replay ever fell through to a live model, the run would crash. It never does: the
                test suite, the CI regression job and the demo script all replay to the same final
                state as the recording, with the tripwire left untouched.
              </p>
              <ul className="mt-5 space-y-2 text-sm">
                <li>✓ 100 unit + integration tests</li>
                <li>✓ Golden-trace regression suite on every push</li>
                <li>✓ Replay reproduces the recorded final state exactly</li>
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
        <Section id="use" eyebrow="07 · Use it" title="Three snippets">
          <div className="grid gap-4 lg:grid-cols-3">
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

          <div className="mt-10 rounded-2xl border border-border bg-surface-2 p-6">
            <h3 className="font-semibold text-fg">Known limits (v1)</h3>
            <ul className="mt-3 grid gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2">
              <li>· LangGraph only. CrewAI / raw OpenAI support is planned.</li>
              <li>· Replay assumes read-mostly tools. Writes aren&apos;t sandboxed.</li>
              <li>· Replays final messages, not token streams.</li>
              <li>· Renaming a graph node shows up as a structural diff.</li>
            </ul>
          </div>

          <div className="mt-10 flex flex-wrap items-center gap-3">
            <Link
              href="/"
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg shadow-sm transition-opacity hover:opacity-90"
            >
              Open the trace viewer →
            </Link>
            <a
              href="https://github.com/hassanzafarr/AgentReplay"
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-fg transition-colors hover:bg-surface-3"
            >
              View source on GitHub
            </a>
          </div>
        </Section>
      </main>

      <footer className="border-t border-border py-8 text-center text-xs text-fg-subtle">
        AgentReplay · MIT · built by Hassan Zafar
      </footer>
    </div>
  );
}

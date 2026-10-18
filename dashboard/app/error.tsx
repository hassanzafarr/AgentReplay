"use client";

// Last line of defence: validateTrace should stop malformed files at the drop zone, but if
// anything still throws while rendering, show a recovery screen instead of a blank page.
export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <main className="grid min-h-screen place-items-center bg-desk p-6">
      <div role="alert" className="punchcard flex w-full max-w-md">
        <div className="flex flex-1 flex-col gap-4 p-6">
          <h1 className="cardprint text-xl font-extrabold text-print">The viewer jammed</h1>
          <p className="text-sm text-ink">
            Something in the loaded trace couldn&apos;t be displayed. Your files stay on your machine;
            nothing was uploaded. Start over to load a different trace.
          </p>
          {error.message && (
            <pre className="listing-plain overflow-auto whitespace-pre-wrap border border-card-line p-3 font-mono text-xs">
              {error.message}
            </pre>
          )}
          <div className="flex flex-wrap items-center gap-4">
            <button
              type="button"
              onClick={reset}
              className="bg-ink px-4 py-2 text-sm font-semibold text-card transition-opacity hover:opacity-90"
            >
              Start over
            </button>
            <a
              href="https://github.com/hassanzafarr/AgentReplay/issues"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm font-semibold text-ink underline underline-offset-4"
            >
              Report the problem
            </a>
          </div>
        </div>
      </div>
    </main>
  );
}

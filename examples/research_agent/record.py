"""Record example traces for the regression demo.

Run once from the repo root to generate .trace.json files::

    python -m examples.research_agent.record

This uses StandInModel (no API key needed). Swap it for ChatAnthropic
or any BaseChatModel to record real production traces.
"""

from __future__ import annotations

from pathlib import Path

import agentreplay
from examples.research_agent.agent import StandInModel, build_agent

TRACES_DIR = Path(__file__).parent / "traces"

EXAMPLE_INPUTS = [
    {"topic": "carbon capture and storage", "research": "", "brief": ""},
    {"topic": "AI safety and alignment", "research": "", "brief": ""},
    {"topic": "quantum computing applications", "research": "", "brief": ""},
]


def main() -> None:
    print(f"Recording {len(EXAMPLE_INPUTS)} traces to {TRACES_DIR}/")

    for inp in EXAMPLE_INPUTS:
        wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=StandInModel(),
            mode="record",
            trace_dir=TRACES_DIR,
            metadata={"source": "example", "topic": inp["topic"]},
        )
        result = wrapped.invoke(inp)
        print(f"  Recorded: {inp['topic']!r} → {wrapped.last_trace_path.name}")
        print(f"    research: {result['research'][:60]}…")
        print(f"    brief:    {result['brief'][:60]}…")

    print(f"\nDone. Run: pytest examples/research_agent/ -v")


if __name__ == "__main__":
    main()

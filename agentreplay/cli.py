"""Command-line interface for AgentReplay.

Commands::

    agentreplay diff <trace_a> <trace_b>   Compare two trace files
    agentreplay show <trace>               Display trace events

Record and replay are done programmatically via ``agentreplay.wrap()``
and ``agentreplay.ReplayEngine``. The CLI focuses on trace inspection and
diffing, which require no knowledge of the agent's build function.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _cmd_diff(args: argparse.Namespace) -> int:
    from agentreplay.recorder.trace_writer import TraceWriter
    from agentreplay.replayer.divergence import diff_traces

    path_a = Path(args.trace_a)
    path_b = Path(args.trace_b)

    for p in (path_a, path_b):
        if not p.exists():
            print(f"error: trace file not found: {p}", file=sys.stderr)
            return 1

    trace_a = TraceWriter.read(path_a)
    trace_b = TraceWriter.read(path_b)

    report = diff_traces(trace_a, trace_b)
    print(report.format_report())
    return 0 if report.is_identical else 1


def _cmd_show(args: argparse.Namespace) -> int:
    from agentreplay.recorder.trace_writer import TraceWriter

    path = Path(args.trace)
    if not path.exists():
        print(f"error: trace file not found: {path}", file=sys.stderr)
        return 1

    trace = TraceWriter.read(path)
    events = sorted(trace.events, key=lambda e: e.seq)

    print(f"Trace: {trace.run_id}")
    print(f"Created: {trace.created_at.isoformat()}")
    print(f"Events: {len(events)}")
    if trace.metadata:
        print(f"Metadata: {json.dumps(trace.metadata)}")
    print()

    for event in events:
        etype = event.event_type.value
        seq = event.seq

        if etype == "llm_call":
            prompt = event.input_messages[0].content[:60] if event.input_messages else "?"
            output = event.output[:60] if event.output else "?"
            print(f"  [{seq:3d}] llm_call  hash={event.hash[:8]}…")
            print(f"         in:  {prompt!r}")
            print(f"         out: {output!r}")

        elif etype == "tool_call":
            args_preview = str(event.input_args)[:60]
            out_preview = event.output[:60] if event.output else ""
            status = "ERR" if event.error else "OK"
            print(f"  [{seq:3d}] tool_call tool={event.tool_name}  [{status}]")
            print(f"         in:  {args_preview}")
            print(f"         out: {out_preview!r}")

        elif etype == "clock":
            print(f"  [{seq:3d}] clock     {event.recorded_time.isoformat()}")

        elif etype == "random":
            print(f"  [{seq:3d}] random    source={event.source}  value={event.value}")

        else:
            print(f"  [{seq:3d}] {etype}")

    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import subprocess
    import shutil

    dashboard_dir = Path(__file__).parent.parent / "dashboard"
    if not dashboard_dir.exists():
        print(
            "error: dashboard/ directory not found.\n"
            "       Run from the AgentReplay repo root, or install the full package.",
            file=sys.stderr,
        )
        return 1

    if shutil.which("npm") is None:
        print("error: npm not found. Install Node.js from https://nodejs.org/", file=sys.stderr)
        return 1

    node_modules = dashboard_dir / "node_modules"
    if not node_modules.exists():
        print("Installing dashboard dependencies (first run only)…")
        result = subprocess.run(["npm", "install"], cwd=str(dashboard_dir))
        if result.returncode != 0:
            print("error: npm install failed.", file=sys.stderr)
            return result.returncode

    port = args.port
    print(f"Starting AgentReplay dashboard on http://localhost:{port}")
    print("Drag a .trace.json file into the browser to inspect it.")
    print("Press Ctrl+C to stop.")
    try:
        subprocess.run(
            ["npm", "run", "dev", "--", "--port", str(port)],
            cwd=str(dashboard_dir),
        )
    except KeyboardInterrupt:
        pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="agentreplay",
        description="Deterministic record/replay for LangGraph agents.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    # diff ----------------------------------------------------------------
    diff_p = subparsers.add_parser(
        "diff",
        help="Compare two trace files and report divergences.",
    )
    diff_p.add_argument("trace_a", metavar="TRACE_A", help="First trace file")
    diff_p.add_argument("trace_b", metavar="TRACE_B", help="Second trace file")

    # show ----------------------------------------------------------------
    show_p = subparsers.add_parser(
        "show",
        help="Display trace events in human-readable form.",
    )
    show_p.add_argument("trace", metavar="TRACE", help="Trace file to display")

    # serve ---------------------------------------------------------------
    serve_p = subparsers.add_parser(
        "serve",
        help="Start the visual dashboard (Next.js) on localhost.",
    )
    serve_p.add_argument(
        "--port", type=int, default=3000, metavar="PORT",
        help="Port to listen on (default: 3000).",
    )

    args = parser.parse_args()

    if args.command == "diff":
        return _cmd_diff(args)
    if args.command == "show":
        return _cmd_show(args)
    if args.command == "serve":
        return _cmd_serve(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

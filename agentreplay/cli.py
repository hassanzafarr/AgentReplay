"""Command-line interface for AgentReplay.

Commands::

    agentreplay diff <trace_a> <trace_b>   Compare two trace files
    agentreplay show <trace>               Display trace events
    agentreplay export <trace|dir>...      Send traces to an OTel backend / Langfuse
    agentreplay serve                      Start the visual dashboard

Record and replay are done programmatically via ``agentreplay.wrap()``
and ``agentreplay.ReplayEngine``. The CLI focuses on trace inspection and
diffing, which require no knowledge of the agent's build function.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Traces older than this trigger a retention warning on export.
_STALE_TRACE_DAYS = 7


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


def _v2_summary(event) -> str:
    """Node, latency, model and tokens (schema v2); empty for v1 events."""
    parts = []
    if getattr(event, "node", None):
        parts.append(f"node={event.node}")
    if getattr(event, "duration_ms", None) is not None:
        parts.append(f"{event.duration_ms:.0f}ms")
    if getattr(event, "model_id", None):
        parts.append(f"model={event.model_id}")
    usage = getattr(event, "usage", None)
    if usage is not None:
        parts.append(f"tokens={usage.input_tokens}→{usage.output_tokens}")
    return "  ".join(parts)


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
            print(f"  [{seq:3d}] llm_call  hash={event.hash[:8]}…  {_v2_summary(event)}".rstrip())
            print(f"         in:  {prompt!r}")
            print(f"         out: {output!r}")

        elif etype == "tool_call":
            args_preview = str(event.input_args)[:60]
            out_preview = event.output[:60] if event.output else ""
            status = "ERR" if event.error else "OK"
            print(f"  [{seq:3d}] tool_call tool={event.tool_name}  [{status}]  {_v2_summary(event)}".rstrip())
            print(f"         in:  {args_preview}")
            print(f"         out: {out_preview!r}")

        elif etype == "clock":
            print(f"  [{seq:3d}] clock     {event.recorded_time.isoformat()}")

        elif etype == "random":
            print(f"  [{seq:3d}] random    source={event.source}  value={event.value}")

        else:
            print(f"  [{seq:3d}] {etype}")

    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    from agentreplay.integrations.otel import (
        INSTALL_HINT,
        ResultTrackingExporter,
        export_trace,
        langfuse_otlp_config,
        otlp_tracer_provider,
    )
    from agentreplay.recorder.trace_writer import TraceWriter

    # Resolve inputs: files as-is, directories → every *.trace.json inside.
    paths: list[Path] = []
    for raw in args.traces:
        p = Path(raw)
        if p.is_dir():
            paths.extend(sorted(p.glob("*.trace.json")))
        elif p.exists():
            paths.append(p)
        else:
            print(f"error: trace file not found: {p}", file=sys.stderr)
            return 1
    if not paths:
        print("error: no .trace.json files found", file=sys.stderr)
        return 1

    headers: dict[str, str] = {}
    for item in args.header:
        key, sep, value = item.partition("=")
        if not sep or not key:
            print(f"error: --header must be KEY=VALUE, got {item!r}", file=sys.stderr)
            return 1
        headers[key.strip()] = value.strip()

    try:
        if args.console:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter

            inner = ConsoleSpanExporter(out=sys.stdout)
            target = "console"
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            endpoint = args.endpoint
            if args.langfuse:
                try:
                    endpoint, langfuse_headers = langfuse_otlp_config()
                except ValueError as exc:
                    print(f"error: {exc}", file=sys.stderr)
                    return 1
                headers = {**langfuse_headers, **headers}
            inner = OTLPSpanExporter(endpoint=endpoint, headers=headers or None)
            target = endpoint or "endpoint from OTEL_EXPORTER_OTLP_* env"
    except ImportError:
        print(f"error: {INSTALL_HINT}", file=sys.stderr)
        return 1

    tracker = ResultTrackingExporter(inner)
    provider = otlp_tracer_provider(exporter=tracker, service_name=args.service_name)

    # Status lines go to stderr so --console leaves stdout as pure span JSON.
    read_errors = 0
    for path in paths:
        try:
            trace = TraceWriter.read(path)
        except Exception as exc:
            print(f"error: could not read {path}: {exc}", file=sys.stderr)
            read_errors += 1
            continue
        age = datetime.now(timezone.utc) - trace.created_at
        if not args.shift_to_now and age > timedelta(days=_STALE_TRACE_DAYS):
            # Backends drop spans older than their retention window without
            # any error, so the export "succeeds" but never shows up.
            print(
                f"warning: {path.name} was recorded {age.days} days ago; backends with "
                "data retention (e.g. Langfuse Cloud) may silently drop it. "
                "Use --shift-to-now to export it at the current time.",
                file=sys.stderr,
            )
        trace_id = export_trace(
            trace,
            tracer_provider=provider,
            include_content=args.include_content,
            environment=args.environment,
            shift_to_now=args.shift_to_now,
        )
        print(f"exported {path.name} -> trace_id {trace_id}", file=sys.stderr)

    provider.force_flush()
    provider.shutdown()

    if tracker.failed:
        print(f"error: backend rejected or unreachable: {target}", file=sys.stderr)
        return 1
    exported = len(paths) - read_errors
    print(f"{exported} trace(s) sent to {target}", file=sys.stderr)
    return 1 if read_errors else 0


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


def _ensure_utf8_stdout() -> None:
    """Reports contain emoji/box-drawing chars; Windows consoles default to
    cp1252 and raise UnicodeEncodeError on them. Switch to UTF-8 and replace
    anything the terminal still can't render instead of crashing."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    _ensure_utf8_stdout()
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

    # export --------------------------------------------------------------
    export_p = subparsers.add_parser(
        "export",
        help="Send traces as OpenTelemetry spans (OTLP, Langfuse, or console).",
    )
    export_p.add_argument(
        "traces", metavar="TRACE", nargs="+",
        help="Trace file(s) or directories of *.trace.json files.",
    )
    dest = export_p.add_mutually_exclusive_group()
    dest.add_argument(
        "--endpoint", metavar="URL",
        help="OTLP/HTTP traces URL (default: OTEL_EXPORTER_OTLP_* env, "
             "else http://localhost:4318/v1/traces).",
    )
    dest.add_argument(
        "--langfuse", action="store_true",
        help="Send to Langfuse using LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY "
             "/ LANGFUSE_BASE_URL from the environment.",
    )
    dest.add_argument(
        "--console", action="store_true",
        help="Print spans to stdout instead of sending them.",
    )
    export_p.add_argument(
        "--header", action="append", default=[], metavar="KEY=VALUE",
        help="Extra HTTP header for the OTLP request (repeatable).",
    )
    export_p.add_argument(
        "--include-content", action="store_true",
        help="Also export prompts, completions and tool I/O (off by default: "
             "content may contain PII).",
    )
    export_p.add_argument(
        "--environment", metavar="NAME",
        help="Tag every span with deployment.environment.name (e.g. 'replay', 'ci').",
    )
    export_p.add_argument(
        "--shift-to-now", action="store_true",
        help="Move each run to the current time, keeping relative timing. Use for "
             "old/golden traces: backends with data retention drop old spans silently.",
    )
    export_p.add_argument(
        "--service-name", default="agentreplay", metavar="NAME",
        help="OTel service.name resource attribute (default: agentreplay).",
    )

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
    if args.command == "export":
        return _cmd_export(args)
    if args.command == "serve":
        return _cmd_serve(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

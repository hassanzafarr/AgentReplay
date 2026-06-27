"""Tool call interception for LangChain ``BaseTool`` instances.

Wraps a tool so that every invocation (sync and async) is captured as a
``ToolCallEvent``. The wrapper preserves the tool's name, description, and
args schema — which matters because the LLM uses the schema to decide
which tools to call and with what arguments.

v1 limitation (plan §7.4): we record the tool's *output* but do NOT
sandbox its *side effects* (DB writes, file mutations). Replay assumes
read-mostly tools. Write-tool sandboxing is future work.

Implementation note: we wrap at the ``func`` level (the raw Python
callable), not ``_run``, because ``_run`` in newer langchain-core versions
requires a ``config`` keyword argument injected by the framework. Wrapping
``func`` avoids fighting the framework's internal plumbing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import wraps
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from agentreplay.recorder.collector import TraceCollector
from agentreplay.schema.trace import ToolCallEvent, content_hash


def wrap_tool(tool: BaseTool, collector: TraceCollector) -> BaseTool:
    """Return a copy of *tool* whose underlying function is instrumented.

    The returned tool has the same name, description, and schema as the
    original — only the execution path is wrapped to capture events.
    """
    if not isinstance(tool, StructuredTool):
        # For non-StructuredTool instances, fall back to wrapping invoke().
        return _wrap_via_invoke(tool, collector)

    # StructuredTool stores the raw callable in `.func` and `.coroutine`.
    # Wrapping these is safe and avoids the _run(config=...) issue.
    original_func = tool.func
    original_coroutine = tool.coroutine

    if original_func is not None:
        @wraps(original_func)
        def instrumented_func(*args: Any, **kwargs: Any) -> Any:
            input_args = _normalize_args(args, kwargs)
            tool_hash = content_hash({"tool": tool.name, "input": input_args})

            error_msg: str | None = None
            output: str = ""
            try:
                result = original_func(*args, **kwargs)
                output = str(result)
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                event = ToolCallEvent(
                    seq=collector.next_seq(),
                    hash=tool_hash,
                    tool_name=tool.name,
                    input_args=input_args,
                    output=output,
                    error=error_msg,
                )
                collector.add_event(event)

            return result

        tool.func = instrumented_func

    if original_coroutine is not None:
        @wraps(original_coroutine)
        async def instrumented_coroutine(*args: Any, **kwargs: Any) -> Any:
            input_args = _normalize_args(args, kwargs)
            tool_hash = content_hash({"tool": tool.name, "input": input_args})

            error_msg: str | None = None
            output: str = ""
            try:
                result = await original_coroutine(*args, **kwargs)
                output = str(result)
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                event = ToolCallEvent(
                    seq=collector.next_seq(),
                    hash=tool_hash,
                    tool_name=tool.name,
                    input_args=input_args,
                    output=output,
                    error=error_msg,
                )
                collector.add_event(event)

            return result

        tool.coroutine = instrumented_coroutine

    return tool


def _wrap_via_invoke(tool: BaseTool, collector: TraceCollector) -> BaseTool:
    """Fallback wrapper for non-StructuredTool instances.

    Wraps the public ``invoke()`` method instead of internal ``_run()``.
    """
    original_invoke = tool.invoke

    def instrumented_invoke(input: Any, **kwargs: Any) -> Any:
        input_args = {"input": _safe_serialize(input)}
        tool_hash = content_hash({"tool": tool.name, "input": input_args})

        error_msg: str | None = None
        output: str = ""
        try:
            result = original_invoke(input, **kwargs)
            output = str(result)
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            event = ToolCallEvent(
                seq=collector.next_seq(),
                hash=tool_hash,
                tool_name=tool.name,
                input_args=input_args,
                output=output,
                error=error_msg,
            )
            collector.add_event(event)

        return result

    tool.invoke = instrumented_invoke  # type: ignore[assignment]
    return tool


def _normalize_args(args: tuple, kwargs: dict) -> dict[str, Any]:
    """Convert positional + keyword args into a JSON-serializable dict."""
    result: dict[str, Any] = {}
    if args:
        result["_positional"] = [_safe_serialize(a) for a in args]
    for k, v in kwargs.items():
        # Filter out LangChain internal kwargs that aren't meaningful for replay.
        if k in ("run_manager", "config", "callbacks"):
            continue
        result[k] = _safe_serialize(v)
    return result


def _safe_serialize(value: Any) -> Any:
    """Best-effort serialization of arbitrary tool arguments."""
    try:
        json.dumps(value)
        return value  # Already serializable.
    except (TypeError, ValueError):
        return str(value)

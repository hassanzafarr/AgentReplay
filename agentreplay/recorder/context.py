"""Per-call context captured alongside events (schema v2): timing and node.

Kept separate from the interceptors so the LLM wrapper, the tool wrapper and
the replay engine all record these the same way.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any


class CallTimer:
    """Wall-clock start time plus a monotonic duration for one call.

    ``start_ts`` places the call on a timeline (OTel spans, dashboards);
    ``duration_ms`` comes from ``perf_counter`` so clock adjustments during
    the call can't produce negative or inflated latency.
    """

    def __init__(self) -> None:
        self.start_ts = datetime.now(timezone.utc)
        self._t0 = time.perf_counter()

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0


def current_node(run_manager: Any = None) -> str | None:
    """Name of the LangGraph node currently executing, or ``None``.

    LangGraph stamps ``langgraph_node`` into the runnable config's metadata.
    Chat models usually see it on their callback ``run_manager``; tools (and
    sync models called from async nodes) only see it via LangChain's
    child-config context var, so we fall back to that. Outside a graph both
    are empty and the event simply has no node.
    """
    metadata = getattr(run_manager, "metadata", None) or {}
    node = metadata.get("langgraph_node")
    if node:
        return str(node)

    try:
        from langchain_core.runnables.config import var_child_runnable_config
    except ImportError:  # pragma: no cover - very old langchain-core
        return None
    config = var_child_runnable_config.get() or {}
    node = (config.get("metadata") or {}).get("langgraph_node")
    return str(node) if node else None

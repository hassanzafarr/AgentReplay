"""Serializes a ``Trace`` to a JSON file on disk.

One file per run, named ``<run_id>.trace.json`` by default. The file is
a valid JSON document that round-trips through Pydantic (write → read →
validate → identical object).
"""

from __future__ import annotations

import json
from pathlib import Path

from agentreplay.schema.trace import Trace


class TraceWriter:
    """Writes trace objects to disk as JSON files."""

    def __init__(self, trace_dir: str | Path = "./traces") -> None:
        self._trace_dir = Path(trace_dir)

    def write(self, trace: Trace, *, compact: bool = False) -> Path:
        """Serialize *trace* to a JSON file and return its path.

        Args:
            trace: The completed trace to persist.
            compact: If True, write minified JSON. Otherwise pretty-print
                for human readability (default).

        Returns:
            The ``Path`` to the written file.
        """
        self._trace_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{trace.run_id}.trace.json"
        path = self._trace_dir / filename

        data = trace.model_dump(mode="json")

        indent = None if compact else 2
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False, default=str)

        return path

    @staticmethod
    def read(path: str | Path) -> Trace:
        """Load and validate a trace from a JSON file.

        Raises ``pydantic.ValidationError`` if the file doesn't match the
        schema — this is intentional; a corrupted trace should fail loudly.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Trace.model_validate(data)

"""pytest plugin — turns .trace.json files into regression tests.

When the plugin is active, it collects every ``.trace.json`` file under the
configured traces directory. Each trace becomes an independent pytest test
item that:

1. Replays the agent against current code (zero live LLM calls).
2. Passes if the event sequence is identical to the recording.
3. Fails with a human-readable divergence report if anything changed.

Configuration (``pyproject.toml`` or ``pytest.ini``)::

    [tool.pytest.ini_options]
    agentreplay_traces = "traces/"
    agentreplay_agent  = "myagent.build:build_agent"
    agentreplay_model  = "myagent.build:get_model"   # optional

Or via CLI::

    pytest --agentreplay-traces=traces/ --agentreplay-agent=myagent.build:build_agent

The ``agentreplay_agent`` value is a ``module.path:function_name`` string that
must resolve to a callable matching one of these signatures::

    def build_agent(model) -> CompiledGraph: ...
    def build_agent(model, tools) -> CompiledGraph: ...

The input used for replay is read from ``trace.metadata["_agentreplay_input"]``,
which ``agentreplay.wrap()`` stores automatically at record time.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from agentreplay.recorder.trace_writer import TraceWriter
from agentreplay.replayer.divergence import DivergenceReport
from agentreplay.replayer.replay_engine import ReplayEngine
from agentreplay.schema.trace import Trace


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _import_callable(spec: str) -> Any:
    """Import ``module.path:attr_name`` and return the attribute."""
    module_path, _, attr = spec.partition(":")
    if not attr:
        raise ValueError(
            f"Invalid agent spec {spec!r} — expected 'module.path:function_name'"
        )
    module = importlib.import_module(module_path)
    return getattr(module, attr)


def _make_null_model():
    """Instantiate a NullModel (constructed lazily to avoid import-time cost)."""
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatResult

    class NullModel(BaseChatModel):
        model_config = {"arbitrary_types_allowed": True}

        @property
        def _llm_type(self) -> str:
            return "null_replay"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise RuntimeError(
                "AgentReplay pytest plugin: live LLM call reached during replay.\n"
                "This means a prompt hash miss — the recorded response was not found.\n"
                "Check the divergence report for details."
            )

    return NullModel()


class TraceRegressionError(Exception):
    """Raised when a replay diverges from its recording."""

    def __init__(self, report: DivergenceReport) -> None:
        self.report = report
        super().__init__(report.summary)


# ---------------------------------------------------------------------------
# Plugin config holder
# ---------------------------------------------------------------------------

class _AgentReplayPlugin:
    """Holds resolved configuration for the test session."""

    def __init__(
        self,
        traces_dir: Path,
        agent_spec: str,
        model_spec: str | None,
        rootpath: Path | None = None,
    ) -> None:
        self.traces_dir = traces_dir.resolve()
        self.agent_spec = agent_spec
        self.model_spec = model_spec
        # rootpath is inserted into sys.path before importing user modules so
        # the plugin works when pytest is run from a project directory where
        # user modules live (e.g. in pytester isolated sessions).
        self._rootpath = rootpath

    def _ensure_rootpath(self) -> None:
        """Insert rootpath into sys.path if not already present."""
        import sys
        if self._rootpath is not None:
            rp = str(self._rootpath)
            if rp not in sys.path:
                sys.path.insert(0, rp)

    def build_fn(self):
        self._ensure_rootpath()
        return _import_callable(self.agent_spec)

    def model(self):
        self._ensure_rootpath()
        if self.model_spec:
            factory = _import_callable(self.model_spec)
            return factory()
        return _make_null_model()


# ---------------------------------------------------------------------------
# Pytest hooks
# ---------------------------------------------------------------------------

def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("agentreplay", "AgentReplay regression testing")
    group.addoption(
        "--agentreplay-traces",
        dest="agentreplay_traces",
        default=None,
        metavar="DIR",
        help="Directory of .trace.json regression files.",
    )
    group.addoption(
        "--agentreplay-agent",
        dest="agentreplay_agent",
        default=None,
        metavar="MODULE:FUNC",
        help="Build function for the LangGraph agent (module.path:function).",
    )
    group.addoption(
        "--agentreplay-model",
        dest="agentreplay_model",
        default=None,
        metavar="MODULE:FUNC",
        help="Optional model factory (module.path:function -> BaseChatModel).",
    )

    parser.addini(
        "agentreplay_traces",
        help="Directory of .trace.json files.",
        default=None,
    )
    parser.addini(
        "agentreplay_agent",
        help="'module.path:function' build function for the LangGraph agent.",
        default=None,
    )
    parser.addini(
        "agentreplay_model",
        help="Optional 'module.path:function' model factory.",
        default=None,
    )


def pytest_configure(config: pytest.Config) -> None:
    # Prefer CLI options; fall back to ini values.
    def _get(opt: str) -> str | None:
        cli = config.getoption(opt, default=None)
        return cli or config.getini(opt) or None

    traces = _get("agentreplay_traces")
    agent = _get("agentreplay_agent")
    model = _get("agentreplay_model")

    if traces and agent:
        config._agentreplay = _AgentReplayPlugin(
            traces_dir=Path(traces),
            agent_spec=agent,
            model_spec=model,
            rootpath=getattr(config, "rootpath", None),
        )
    else:
        config._agentreplay = None


def pytest_collect_file(
    parent: pytest.Collector,
    file_path: Path,
) -> pytest.Collector | None:
    plugin: _AgentReplayPlugin | None = getattr(parent.config, "_agentreplay", None)
    if plugin is None:
        return None

    if (
        file_path.suffix == ".json"
        and ".trace" in file_path.name
        and file_path.resolve().is_relative_to(plugin.traces_dir)
    ):
        return TraceFile.from_parent(parent, path=file_path)

    return None


# ---------------------------------------------------------------------------
# Custom collector + test item
# ---------------------------------------------------------------------------

class TraceFile(pytest.File):
    """Collector for a single .trace.json file."""

    def collect(self):
        plugin: _AgentReplayPlugin = self.config._agentreplay
        trace_name = self.path.name.replace(".trace.json", "")
        yield TraceItem.from_parent(
            self,
            name=trace_name,
            trace_path=self.path,
            plugin=plugin,
        )


class TraceItem(pytest.Item):
    """A single regression test backed by a recorded trace.

    Passes  → replay is structurally + tool-call identical to recording.
    Fails   → divergence detected; report shows exactly what changed.
    """

    def __init__(
        self,
        *,
        name: str,
        parent: pytest.Collector,
        trace_path: Path,
        plugin: _AgentReplayPlugin,
    ) -> None:
        super().__init__(name=name, parent=parent)
        self._trace_path = trace_path
        self._plugin = plugin
        self._report: DivergenceReport | None = None

    def runtest(self) -> None:
        trace: Trace = TraceWriter.read(self._trace_path)

        replay_input: dict = trace.metadata.get("_agentreplay_input", {})

        engine = ReplayEngine(
            recorded_trace=trace,
            build_fn=self._plugin.build_fn(),
            model=self._plugin.model(),
        )
        result = engine.run(replay_input)
        self._report = result.divergence_report

        if not result.divergence_report.is_identical:
            raise TraceRegressionError(result.divergence_report)

    def repr_failure(self, excinfo: pytest.ExceptionInfo) -> str:
        if isinstance(excinfo.value, TraceRegressionError):
            return excinfo.value.report.format_report()
        return super().repr_failure(excinfo)

    def reportinfo(self) -> tuple:
        return (
            self._trace_path,
            None,
            f"agentreplay: {self._trace_path.name}",
        )

"""pytest configuration for the research_agent regression suite.

Runs automatically when pytest collects this directory. If the traces/
directory is empty (first run), it auto-generates example traces using
StandInModel so the demo works without an API key.

Configures the agentreplay plugin for this example::

    agentreplay_agent = "examples.research_agent.agent:build_agent"
    agentreplay_traces = <this directory>/traces/
"""

from __future__ import annotations

from pathlib import Path

import pytest

TRACES_DIR = Path(__file__).parent / "traces"
_AGENT_SPEC = "examples.research_agent.agent:build_agent"


def pytest_configure(config: pytest.Config) -> None:
    """Auto-record traces if traces/ is empty, then configure the plugin.

    Only activates when pytest is run from THIS directory (not from the
    project root), so it doesn't interfere with the main test suite.
    """
    rootpath = getattr(config, "rootpath", None)
    if rootpath is None or Path(rootpath) != Path(__file__).parent:
        return  # Not running from examples/research_agent/ — stay silent.

    # Auto-generate traces if needed (makes demo self-contained).
    if not TRACES_DIR.exists() or not list(TRACES_DIR.glob("*.trace.json")):
        _auto_record()

    # Configure the agentreplay plugin for this directory.
    # This mirrors what a user would put in their pyproject.toml.
    if not config.getini("agentreplay_traces"):
        config._agentreplay_override_traces = str(TRACES_DIR)
        config._agentreplay_override_agent = _AGENT_SPEC


def pytest_sessionstart(session: pytest.Session) -> None:
    # Apply overrides set in pytest_configure (after plugin is initialized).
    overrides_traces = getattr(session.config, "_agentreplay_override_traces", None)
    overrides_agent = getattr(session.config, "_agentreplay_override_agent", None)

    if overrides_traces and overrides_agent:
        from agentreplay.integrations.pytest_plugin import _AgentReplayPlugin
        session.config._agentreplay = _AgentReplayPlugin(
            traces_dir=Path(overrides_traces),
            agent_spec=overrides_agent,
            model_spec=None,
            rootpath=Path(__file__).parent.parent.parent,
        )


def _auto_record() -> None:
    """Generate example traces using StandInModel (no API key needed)."""
    import agentreplay
    from examples.research_agent.agent import StandInModel, build_agent

    TRACES_DIR.mkdir(exist_ok=True)

    inputs = [
        {"topic": "carbon capture and storage", "research": "", "brief": ""},
        {"topic": "AI safety and alignment", "research": "", "brief": ""},
    ]
    for inp in inputs:
        wrapped = agentreplay.wrap(
            build_fn=build_agent,
            model=StandInModel(),
            mode="record",
            trace_dir=TRACES_DIR,
            metadata={"source": "auto-generated-example"},
        )
        wrapped.invoke(inp)

"""CLI output formatting."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from toolkit import __main__ as cli
from toolkit.brain.agent import AgentResult


def _render_ask(monkeypatch, *, verbose: bool) -> str:
    output = StringIO()
    monkeypatch.setattr(
        cli,
        "console",
        Console(file=output, width=48, force_terminal=False),
    )
    monkeypatch.setattr(
        cli,
        "run_agent_sync",
        lambda *args, **kwargs: AgentResult(
            ok=True,
            answer="The answer is 42.",
            trail=[{
                "step": 1,
                "tool": "count_distinct",
                "result": "42 distinct values",
            }],
            steps=1,
            seconds=0.25,
        ),
    )

    cli.ask("question", quiet=False, verbose=verbose)
    return output.getvalue()


def test_cli_hides_tool_trace_by_default(monkeypatch):
    output = _render_ask(monkeypatch, verbose=False)

    assert "The answer is 42." in output
    assert "count_distinct" not in output
    assert "╭" not in output
    assert "0.25s (1 step)" in output


def test_cli_shows_tool_trace_with_verbose(monkeypatch):
    output = _render_ask(monkeypatch, verbose=True)

    assert "Steps" in output
    assert "count_distinct" in output
    assert "42 distinct values" in output

"""Toolkit CLI.

    python -m toolkit ask "how many rows in Sales?"
    python -m toolkit tools list
    python -m toolkit tools run count_rows
    python -m toolkit keys list
    python -m toolkit keys add gsk_abc...
    python -m toolkit serve
"""

from __future__ import annotations

import asyncio
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from toolkit import __version__
from toolkit.brain.agent import run_agent_sync
from toolkit.brain.keys import (
    add_key,
    add_many,
    key_pool,
    load_keys,
    remove_key,
    toggle_key,
)
from toolkit.tools.registry import load_tools

import nest_asyncio
nest_asyncio.apply()


app = typer.Typer(
    help="AI toolkit for tabular data — ask questions, run tools, manage keys.",
    no_args_is_help=True,
)
keys_app = typer.Typer(help="Manage API keys", no_args_is_help=True)
tools_app = typer.Typer(help="Run a tool directly", no_args_is_help=True)
app.add_typer(keys_app, name="keys")
app.add_typer(tools_app, name="tools")
console = Console()


# ── ask ───────────────────────────────────────────────────────────────

@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="The question to ask")],
    quiet: Annotated[bool, typer.Option("--quiet", "-q",
        help="Only print the answer, no decoration")] = False,
) -> None:
    """Ask the agent a question about your data."""
    result = run_agent_sync(question, source="cli")

    if quiet:
        # Plain text to stdout, nothing else. Pipe-friendly.
        if result.answer:
            print(result.answer)
        elif result.why:
            print(result.why, file=sys.stderr)
            raise typer.Exit(1)
        return

    console.print()
    if result.answer:
        console.print(result.answer)
    elif result.why:
        console.print(f"[red]{result.why}[/red]")

    if result.trail:
        console.print()
        console.print("[dim]─── steps ───[/dim]")
        for step in result.trail:
            tool = step.get("tool") or step.get("note") or "?"
            result_text = str(step.get("result") or "")[:80]
            console.print(f"  [dim]{step.get('step', '?')}.[/dim] {tool}  {result_text}")

    console.print()
    console.print(f"[dim]{result.seconds:.2f}s · {result.steps} steps[/dim]")


# ── keys ──────────────────────────────────────────────────────────────

@keys_app.command("list")
def keys_list() -> None:
    """Show every stored key."""
    keys = load_keys()
    if not keys:
        console.print("[yellow]No keys yet.[/yellow]")
        console.print("Add one with: toolkit keys add <key>")
        return
    table = Table("nickname", "company", "model", "wins", "fails", "state")
    for k in keys:
        state = "on" if k.enabled else "off"
        if k.resting:
            state = "resting"
        table.add_row(
            k.nickname, k.provider, k.model or "—",
            str(k.wins), str(k.fails), state,
        )
    console.print(table)


@keys_app.command("add")
def keys_add(
    pasted: Annotated[str, typer.Argument(
        help="A key, or several, separated by whitespace")],
) -> None:
    """Add one or more API keys."""
    if " " in pasted.strip() or "\n" in pasted:
        result = add_many(pasted)
    else:
        result = add_key("", pasted, "")

    if result.ok:
        console.print(f"[green]✓[/green] {result.nickname}")
        if result.model:
            console.print(f"  using {result.model}")
    else:
        console.print(f"[red]✗[/red] {result.why}")
        raise typer.Exit(1)


@keys_app.command("pool")
def keys_pool() -> None:
    """A company-by-company breakdown."""
    console.print(key_pool())


@keys_app.command("remove")
def keys_remove(
    key_id: Annotated[str, typer.Argument(help="The key id")],
) -> None:
    """Remove a key by id."""
    removed = remove_key(key_id)
    if removed is None:
        console.print(f"[red]No key with id {key_id}[/red]")
        raise typer.Exit(1)
    console.print(f"Removed {removed.label}")


@keys_app.command("toggle")
def keys_toggle(
    key_id: Annotated[str, typer.Argument(help="The key id")],
) -> None:
    """Turn a key on or off."""
    new_state = toggle_key(key_id)
    console.print("on" if new_state else "off")


# ── tools ─────────────────────────────────────────────────────────────

@tools_app.command("list")
def tools_list() -> None:
    """List every registered tool."""
    tools = load_tools()
    table = Table("name", "needs", "what")
    for name, tool in sorted(tools.items()):
        table.add_row(name, ", ".join(tool.need) or "—", tool.what)
    console.print(table)


@tools_app.command("run")
def tools_run(
    name: Annotated[str, typer.Argument(help="Tool name")],
    arg: Annotated[list[str] | None, typer.Option(
        "--arg", "-a", help="key=value pair (repeatable)")] = None,
) -> None:
    """Run one tool directly and print its output."""
    tools = load_tools()
    tool = tools.get(name)
    if tool is None:
        console.print(f"[red]No tool called {name}[/red]")
        raise typer.Exit(1)

    args: dict[str, str] = {}
    for pair in arg or []:
        if "=" not in pair:
            console.print(f"[red]Bad arg {pair!r}. Use key=value.[/red]")
            raise typer.Exit(1)
        key, value = pair.split("=", 1)
        args[key] = value

    result = tool.run(args)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    console.print(result)


# ── serve ─────────────────────────────────────────────────────────────

@app.command()
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8000,
    reload: Annotated[bool, typer.Option("--reload")] = False,
) -> None:
    """Run the HTTP server (not implemented yet)."""
    console.print("[yellow]The server is not implemented yet.[/yellow]")
    console.print("For now, use `toolkit ask ...` from the command line.")
    raise typer.Exit(1)


# ── version ───────────────────────────────────────────────────────────

@app.command()
def version() -> None:
    """Print the toolkit version."""
    console.print(f"toolkit {__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
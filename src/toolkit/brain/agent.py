"""The agent loop.

Ported from Code.gs runAgent(). The heart of the toolkit. Given a
question and a set of tools, it:

  1. Tries the direct matchers first (no model needed).
  2. If nothing matches, asks the model what to do.
  3. Runs the tool the model picked.
  4. Feeds the result back.
  5. Repeats up to MAX_STEPS times.
  6. When the model says "I have the answer", verifies the claims
     against what the tools actually returned, and returns.

Differences from the original:

  * No time budget. Apps Script kills at 6 minutes; Python does not.
  * The loop is async, so a future version can run provider calls in
    parallel. Right now it is sequential, same as the original.
  * Every failure path returns a sentence. Nothing raises to the
    caller. `run_agent` is the only entry point a CLI or API needs.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from toolkit.brain.http import call_ai_async, run_sync
from toolkit.brain.presentation import present_direct_answer
from toolkit.brain.history import load_recent, save_turn
from toolkit.brain.verify import (
    check_claims,
    critique,
    invented_something,
)
from toolkit.tools.registry import ToolResult, load_tools, run_direct, tool_said_no

MAX_STEPS = 8

SYSTEM_PROMPT = """You are an assistant that lives alongside a set of
data tabs and a small library of tools. Your job is to answer the
user's question accurately, using the tools when needed.

Each reply you write MUST be JSON ONLY, in one of these two shapes:

    {"thought": "why I am doing this", "tool": "tool_name", "args": {...}}
    {"answer": "your final reply to the user"}

Rules:

  · One tool per step. You will see the result, then decide the next step.
  · When you have enough, reply with {"answer": ...}.
  · Never invent a number. If a tool did not give you a figure, do not
    state one.
  · Preserve the unit named by each tool result. Rows are not necessarily
    distinct orders; only call them orders when the result counts distinct
    Order ID values.
  · If a tool fails twice on the same thing, stop and say so honestly
    in the answer.
  · Answers are under 120 words, plain text. No markdown.
  · If the tools cannot answer the question at all, say so plainly.
"""


@dataclass
class AgentResult:
    """What run_agent returns.

    ok:      the loop completed and produced an answer
    answer:  the text to show the user
    why:     if not ok, why — this is also what the CLI prints
    trail:   the tool calls, in order — used by the Drawer graph
    steps:   how many model turns we used
    seconds: wall-clock duration
    checked: claim-verification result, if the answer was verified
    """

    ok: bool
    answer: str = ""
    why: str = ""
    trail: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    seconds: float = 0.0
    checked: Any = None


async def run_agent(
    request: str,
    *,
    source: str = "api",
    system: str | None = None,
) -> AgentResult:
    """The one entry point. Never raises; always returns a result."""
    started = time.monotonic()

    request = str(request or "").strip()
    if not request:
        return AgentResult(ok=False, why="I did not catch that. Ask again?",
                           seconds=time.monotonic() - started)

    # ── 1. Direct matchers ────────────────────────────────────────────
    direct = run_direct(request)
    if direct is not None:
        answer = (
            present_direct_answer(request, direct.tool, direct.answer)
            if direct.ok else direct.answer
        )

         # Save direct hits to history too
        save_turn("user", request)
        save_turn("assistant", answer)
        
        return AgentResult(
            ok=direct.ok,
            answer=answer,
            why=direct.why,
            trail=[{"step": 1, "tool": direct.tool, "result": direct.answer}],
            steps=1,
            seconds=time.monotonic() - started,
        )
        # ── 2. Model loop ─────────────────────────────────────────────────
    tools = load_tools()
    tool_menu = _tool_menu(tools)

    trail: list[dict[str, Any]] = []
    notes: list[str] = []

    base_system = system or SYSTEM_PROMPT
    full_system = base_system + "\n\nTOOLS YOU MAY USE:\n" + tool_menu
    
    # Load the last 10 turns (5 exchanges) for context
    history = load_recent(10)
    past_turns = [{"role": t.role, "text": t.text} for t in history]

    for step in range(MAX_STEPS):
        prompt = _build_prompt(request, notes)
        try:
            raw = await call_ai_async(prompt, system=full_system, turns=past_turns)
        except Exception as exc:
            return AgentResult(
                ok=False,
                why=f"The model call failed: {exc}",
                trail=trail, steps=step,
                seconds=time.monotonic() - started,
            )

        move = _parse_move(raw)
        if move is None:
            notes.append(
                "Your last reply was not valid JSON. "
                "Reply with JSON only, nothing else."
            )
            trail.append({"step": step + 1, "note": "unreadable reply"})
            continue

        # ── answer ────────────────────────────────────────────────────
        if move.get("answer") is not None:
            answer = str(move["answer"]).strip()
            # Verify against the trail before returning.
            source_text = "\n".join(
                str(t.get("result") or "") for t in trail
            )
            checked = check_claims(answer, source_text)
            invented = invented_something(answer, trail)
            crit = critique(request, answer, source_text)

            if invented is not None:
                answer += "\n\n" + invented.say

            # Save the exchange to history
            save_turn("user", request)
            save_turn("assistant", answer)

            return AgentResult(
                ok=True,
                answer=answer,
                trail=trail,
                steps=step + 1,
                seconds=time.monotonic() - started,
                checked=checked,
            )

        # ── tool call ─────────────────────────────────────────────────
        tool_name = str(move.get("tool") or "")
        if tool_name not in tools:
            notes.append(
                f'Tool "{tool_name}" does not exist. Choose from the menu.'
            )
            trail.append({"step": step + 1, "tool": tool_name,
                          "result": "refused — no such tool"})
            continue

        tool = tools[tool_name]
        args = move.get("args") or {}
        missing = tool.missing(args)
        if missing:
            notes.append(
                f"Tool {tool_name} needs: {', '.join(missing)}. "
                f"Call it again with those."
            )
            trail.append({"step": step + 1, "tool": tool_name,
                          "result": f"missing {', '.join(missing)}"})
            continue

        try:
            result = tool.run(args)
            if asyncio.iscoroutine(result):
                result = await result
        except Exception as exc:
            result = f"That tool failed: {exc}"

        # ToolResult carries its own ok flag; a bare string is
        # classified by tool_said_no(). The trail records the prose
        # either way — the model needs to read what the tool said.
        if isinstance(result, ToolResult):
            result_text = result.prose
            failed = not result.ok
        else:
            result_text = str(result)
            failed = tool_said_no(result_text)

        trail.append({
            "step": step + 1,
            "tool": tool_name,
            "thought": move.get("thought", ""),
            "result": result_text[:220],
            "failed": failed,
        })
        notes.append(
            f"STEP {step + 1} — used {tool_name}\n"
            f"RESULT: {result_text[:2500]}"
        )

    # ── ran out of steps ──────────────────────────────────────────────
    summary = await call_ai_async(
        "Summarise in under 80 words what you did and why you did not "
        "finish. Plain text.\n\n" + "\n\n".join(notes)[:4000],
    )
    return AgentResult(
        ok=False,
        answer=summary if not tool_said_no(summary) else "",
        why="I ran out of steps before finishing.",
        trail=trail, steps=MAX_STEPS,
        seconds=time.monotonic() - started,
    )


def run_agent_sync(request: str, **kwargs: Any) -> AgentResult:
    """Blocking wrapper for the CLI."""
    return run_sync(run_agent(request, **kwargs))


# ── internals ─────────────────────────────────────────────────────────

def _tool_menu(tools: dict[str, Any]) -> str:
    lines = []
    for name, tool in sorted(tools.items()):
        need = f" (needs: {', '.join(tool.need)})" if tool.need else ""
        lines.append(f"  {name} — {tool.what}{need}")
    return "\n".join(lines)


def _build_prompt(request: str, notes: list[str]) -> str:
    if not notes:
        return (
            f"THE USER ASKED:\n{request}\n\n"
            f"What would you like to do? Reply with JSON only."
        )
    return (
        f"THE USER ASKED:\n{request}\n\n"
        f"WHAT YOU HAVE DONE SO FAR:\n"
        + "\n\n".join(notes)
        + "\n\nWhat is your next step? Reply with JSON only."
    )


def _parse_move(raw: str) -> dict[str, Any] | None:
    """Extract the JSON object from the model's reply.

    The model sometimes wraps JSON in ```json fences, or prefixes it
    with prose. Strip both before parsing.
    """
    text = str(raw or "").strip()
    text = text.removeprefix("```json").removeprefix("```")
    text = text.removesuffix("```").strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, dict):
        return None
    return parsed
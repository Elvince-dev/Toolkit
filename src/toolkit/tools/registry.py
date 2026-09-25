"""The tool registry.

Every tool is a Tool dataclass: a name, what it needs, and a function.
The registry assembles the dict the agent loop uses, and also the
matcher that decides when a direct call can bypass the model.

Ported from Code.gs. The differences from the original:

  * The registry is populated by importing modules, not by reading a
    global TOOLS object at file-load time. This avoids the "which
    script file loaded first?" problem that Code.gs has.
  * Tool functions receive a dict of args and return a string, same
    as the original. They can be sync or async; the caller awaits
    whatever comes back.
  * `run_direct` is separate from `load_tools` so the matcher list
    can be tested independently of the tool implementations.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Awaitable, Callable

ToolFn = Callable[[dict[str, Any]], "str | Awaitable[str]"]


@dataclass
class Tool:
    """One capability the agent can invoke.

    name:  unique identifier, e.g. "count_rows"
    what:  a one-line human description, shown to the model
    need:  required argument names. The agent is told what it is
           missing when it forgets one.
    run:   the implementation. Takes a dict, returns a string.
           Sync functions work fine; the caller awaits the result
           whether or not it is a coroutine.
    """

    name: str
    what: str
    need: tuple[str, ...] = ()
    run: ToolFn = field(default=lambda _: "")

    def missing(self, args: dict[str, Any]) -> list[str]:
        return [k for k in self.need if not str(args.get(k) or "").strip()]


@dataclass
class DirectResult:
    ok: bool
    tool: str
    answer: str = ""
    why: str = ""


# ── the registry ──────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_tools() -> dict[str, Tool]:
    """Build the tool dict once, on first call.

    Importing the modules here (inside the function) rather than at
    module top level avoids a circular import: tools import from
    toolkit.tools.registry for the Tool class, but the registry
    builds the dict by importing the tool modules.
    """
    from toolkit.tools import data  # noqa: F401

    out: dict[str, Tool] = {}
    for module in (data,):
        for name, tool in getattr(module, "TOOLS", {}).items():
            if name in out:
                raise RuntimeError(
                    f"Duplicate tool name {name!r} registered in "
                    f"{module.__name__} and another module"
                )
            out[name] = tool
    return out


def reset() -> None:
    """Clear the cached tool dict. Tests call this when monkeypatching."""
    load_tools.cache_clear()


# ── the direct matcher ────────────────────────────────────────────────

@dataclass
class Matcher:
    """One rule for handling a request without calling the model.

    test:  does this request match?
    tool:  which tool to run
    args:  how to build the argument dict from the request text
    soft:  if True, a tool failure falls through to the agent rather
           than being reported. Used for matchers that might be wrong
           about what the user meant.
    """

    name: str
    test: Callable[[str], bool]
    tool: str
    args: Callable[[str], dict[str, Any]]
    soft: bool = False


# Rules are tried in order. The first one that matches wins.
# Deliberately conservative: a wrong match is worse than no match.
MATCHERS: list[Matcher] = [
    Matcher(
        name="count_by",
        test=lambda t: bool(re.search(
            r"\b(which|how many|count|breakdown|break ?down|group)\b"
            r".{0,40}\bby\b", t, re.I)),
        tool="count_by",
        args=lambda t: {
            "tab": _find_tab(t),
            "by": _find_column(t),
        },
    ),
    Matcher(
        name="count_rows",
        test=lambda t: bool(re.search(
            r"\b(how many rows|count (the )?rows|row count|"
            r"how many records)\b", t, re.I)),
        tool="count_rows",
        args=lambda t: {},
    ),
    Matcher(
        name="describe",
        test=lambda t: bool(re.search(
            r"\b(what can you see|describe|what'?s in|what is in|"
            r"show me (the )?sheet|what tabs|list (the )?tabs|"
            r"what columns)\b", t, re.I)),
        tool="describe_sheet",
        args=lambda t: {},
    ),
    Matcher(
        name="outliers",
        test=lambda t: bool(re.search(
            r"\b(outlier|outliers|unusual|strange|anomal|"
            r"stands? out|stand out)\b", t, re.I)),
        tool="find_outliers",
        args=lambda t: {
            "tab": _find_tab(t),
            "column": _find_column(t),
        },
    ),
    Matcher(
        name="groups",
        test=lambda t: bool(re.search(
            r"\b(most|least|highest|lowest|top|biggest|worst|best)\b"
            r".{0,30}\b(by|categor|group|region|branch|type|"
            r"status|kind)\b", t, re.I)),
        tool="compare_groups",
        args=lambda t: {
            "tab": _find_tab(t),
            "column": _find_column(t),
        },
    ),
]


def run_direct(request: str) -> DirectResult | None:
    """Try to answer without the model. Returns None if no rule fits.

    This is what makes `toolkit ask "how many rows in Sales?"` return
    instantly instead of round-tripping to an AI provider. It is also
    how the toolkit works with no key at all.
    """
    text = str(request or "").strip()
    if not text:
        return None

    tools = load_tools()
    for matcher in MATCHERS:
        try:
            if not matcher.test(text):
                continue
        except Exception:
            continue

        tool = tools.get(matcher.tool)
        if tool is None:
            continue

        try:
            args = matcher.args(text) or {}
        except Exception:
            args = {}

        missing = tool.missing(args)
        if missing:
            if matcher.soft:
                return None
            return DirectResult(
                ok=False, tool=tool.name,
                why=(
                    f"I could match that to {tool.name}, but I need "
                    f"{', '.join(missing)} to run it."
                ),
            )

        try:
            result = tool.run(args)
            if asyncio.iscoroutine(result):
                result = asyncio.get_event_loop().run_until_complete(result)
        except Exception as exc:
            if matcher.soft:
                return None
            return DirectResult(
                ok=False, tool=tool.name,
                why=f"The {tool.name} step failed: {exc}",
            )

        text_result = str(result)
        failed = tool_said_no(text_result)
        if failed and matcher.soft:
            return None
        return DirectResult(
            ok=not failed,
            tool=tool.name,
            answer=text_result,
            why=text_result if failed else "",
        )

    return None


# ── helpers ───────────────────────────────────────────────────────────

def tool_said_no(reply: str) -> bool:
    """Does this tool reply mean it failed?

    Ported from toolSaidNo() in Code.gs. Tools reply in prose, so this
    reads the sentence. Erring towards "it failed" is right: a false
    alarm shows a real message; a missed failure claims work that
    never happened.
    """
    t = str(reply or "").strip()
    if not t:
        return True

    # Explicit refusal or requirement anywhere in the reply
    if re.search(r"\b(need|needs|requires?) (a|an|your) [A-Za-z ]{0,24}key\b",
                 t, re.I):
        return True
    if re.search(r"\b(no|not) (a )?(spreadsheet|sheet|tab|data|rows|"
                 r"column|key|permission|access)\b", t, re.I) \
       and "no pivot table was needed" not in t.lower():
        return True

    # Openings that have always meant no
    if re.match(
        r"^(there is no|there are no|no spreadsheet|no data|no key|"
        r"nothing|i could not|i cannot|i can't|i was unable|"
        r"that does not|that did not|which column|which tab|"
        r"column [a-z] is|too few|give me|none of|sorry|unable|"
        r"failed|error)\b",
        t, re.I,
    ):
        return True

    # "It did not return a usable plan" style
    if re.match(
        r"^(it|the [a-z ]{2,20}|this|they|we)\s+"
        r"(did not|does not|could not|cannot|can't|was not|"
        r"were not|is not|are not|would not|will not|never)\b",
        t, re.I,
    ):
        return True
    if re.search(
        r"\b(did not|could not|was unable to)\s+"
        r"(return|produce|build|create|draw|make|find|read|write|"
        r"understand|complete|finish)\b",
        t, re.I,
    ):
        return True

    # Raw exception leaked as text
    if re.match(r"^(TypeError|ReferenceError|Exception|Error)\b", t):
        return True
    if re.search(r"\bcannot read propert(y|ies)\b", t, re.I):
        return True

    return False


def _find_tab(text: str) -> str:
    """Extract a likely tab name from a request.

    Returns "" if nothing obvious. The tools that receive "" fall
    back to their own default (usually the first tab).
    """
    m = re.search(
        r"\b(?:in|from|of|on|for)\s+(?:the\s+)?[\"']?([A-Z][\w .\-]{1,40})[\"']?",
        text,
    )
    if m:
        return m.group(1).strip()
    return ""


def _find_column(text: str) -> str:
    """Extract a likely column name from a request.

    Recognises 'column Amount', 'Amount column', and 'by Amount'.
    Returns "" if nothing obvious.
    """
    m = re.search(r"\bcolumn\s+([A-Z][\w .\-]{1,30})", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"\b([A-Z][\w .\-]{1,30})\s+column\b", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"\bby\s+([A-Z][\w .\-]{1,30})", text)
    if m:
        return m.group(1).strip()
    return ""
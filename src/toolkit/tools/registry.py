"""The tool registry.

Every tool is a Tool dataclass: a name, what it needs, and a function.
The registry assembles the dict the agent loop uses, and also the
matcher that decides when a direct call can bypass the model.

Ported from Code.gs. The differences from the original:

  * The registry is populated by importing modules, not by reading a
    global TOOLS object at file-load time.
  * Tool functions receive a dict of args and return a string. They
    can be sync or async; the caller awaits whatever comes back.
  * `run_direct` is separate from `load_tools` so the matcher list
    can be tested independently of the tool implementations.
  * Every matcher is validated at first use — a matcher that points
    at a nonexistent tool is a bug, not a soft failure.
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
    from toolkit.tools import data, write  # noqa: F401

    out: dict[str, Tool] = {}
    for module in (data, write):
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
    tool:  which tool to run (must be a registered tool name)
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
#
# Order matters:
#   1. summarise_column first — "how much", "total", "average" are
#      specific and would otherwise be swallowed by count/group rules.
#   2. compare_groups_by before count_rows — "count the rows by X"
#      matches both, and the more specific one should win.
#   3. count_rows — the general "how many rows" case.
#   4. describe — shape questions.
#   5. outliers, groups — specialised analytics.
#   6. undo and snapshot — always last, so a word like "restore" in
#      a broader sentence does not hijack the whole request.
MATCHERS: list[Matcher] = [
    Matcher(
        name="group_by_month",
        test=lambda t: bool(re.search(
            r"\b(busiest|quietest|month by month|monthly|"
            r"by month|in january|in february|in march|in april|"
            r"in may|in june|in july|in august|in september|"
            r"in october|in november|in december)\b",
            t, re.I)),
        tool="group_by_month",
        args=lambda t: {
            "tab": _find_tab(t),
            "date_column": _find_column(t),
        },
    ),
    Matcher(
        name="date_range",
        test=lambda t: bool(re.search(
            r"\b(earliest|latest|first and last|date range|"
            r"span|how long)\b.{0,40}\b(date|order|record|entry)\b",
            t, re.I)),
        tool="date_range",
        args=lambda t: {
            "tab": _find_tab(t),
            "column": _find_column(t),
        },
    ),
    Matcher(
        name="summarise_column",
        test=lambda t: bool(re.search(
            r"\b(average|mean|sum|total|how much|max|maximum|"
            r"min|minimum|highest|lowest)\b.{0,40}\b(of|for|in)\b",
            t, re.I)),
        tool="summarise_column",
        args=lambda t: {
            "tab": _find_tab(t),
            "column": _find_column(t),
        },
    ),
    Matcher(
        name="compare_groups_by",
        test=lambda t: bool(re.search(
            r"\b(which|how many|count|breakdown|break ?down|group|"
            r"compare|split|rank)\b.{0,60}\bby\b",
            t, re.I)),
        tool="compare_groups",
        args=lambda t: {
            "tab": _find_tab(t),
            "column": _find_column(t),
        },
    ),
    Matcher(
        name="count_rows_in_named_tab",
        test=lambda t: bool(re.search(
            r"\b(how many rows|count (the )?rows|row count)\b"
            r".{0,40}\b(in|from|of)\b",
            t, re.I)),
        tool="count_rows_in",
        args=lambda t: {"tab": _find_tab(t)},
    ),
    Matcher(
        name="count_distinct",
        test=lambda t: bool(re.search(
            r"\b(how many (unique|distinct|different)|"
            r"count (the )?(unique|distinct)|number of (unique|distinct))\b",
            t, re.I)),
        tool="count_distinct",
        args=lambda t: {
            "tab": _find_tab(t),
            "column": _find_column(t),
        },
    ),
    Matcher(
        name="count_orders_like",
        test=lambda t: bool(re.search(
            r"\bhow many (orders|customers|users|products|sales|"
            r"transactions|invoices|tickets|records)\b",
            t, re.I)),
        tool="count_distinct",
        args=lambda t: {
            "tab": _find_tab(t),
            "column": _singular_to_column(t),
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
    Matcher(
        name="undo",
        test=lambda t: bool(re.search(
            r"\b(undo|take that back|revert|restore)\b", t, re.I)),
        tool="undo_last",
        args=lambda t: {"tab": _find_tab(t)},
    ),
    Matcher(
        name="snapshots",
        test=lambda t: bool(re.search(
            r"\b(snapshots?|undo history)\b", t, re.I)),
        tool="list_snapshots",
        args=lambda t: {"tab": _find_tab(t)},
    ),
]


def _validate_matchers() -> None:
    """Every matcher must point at a real tool.

    A typo in a matcher's tool name is a silent failure: run_direct
    skips the matcher and tries the next one, so the wrong tool runs
    and the user never learns why. This check turns that into a loud
    error at first call instead.
    """
    tools = load_tools()
    for matcher in MATCHERS:
        if matcher.tool not in tools:
            raise RuntimeError(
                f"Matcher {matcher.name!r} points at tool "
                f"{matcher.tool!r}, which is not registered. "
                f"Available: {', '.join(sorted(tools))}"
            )


def run_direct(request: str) -> DirectResult | None:
    """Try to answer without the model. Returns None if no rule fits.

    Validates matchers on first call so a typo in a tool name
    surfaces immediately rather than silently choosing the wrong
    tool.
    """
    text = str(request or "").strip()
    if not text:
        return None

    _validate_matchers()

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
    if re.search(
        r"\b(need|needs|requires?) (a|an|your) [A-Za-z ]{0,24}key\b",
        t, re.I,
    ):
        return True
    if (
        re.search(
            r"\b(no|not) (a )?(spreadsheet|sheet|tab|data|rows|"
            r"column|key|permission|access)\b",
            t, re.I,
        )
        and "no pivot table was needed" not in t.lower()
    ):
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
        r"\b(?:in|from|of|on|for)\s+(?:the\s+)?[\"']?([A-Za-z][\w .\-]{1,40})[\"']?",
        text,
    )
    if m:
        return m.group(1).strip()
    return ""


# Prepositions and punctuation that end a column name. Used by
# _find_column to stop the regex from eating the whole tail of the
# request.
_COLUMN_TAIL = (
    r"([A-Za-z][\w \-]{0,30}?)"
    r"(?=\s+(?:in|from|of|on|for|where|with|about|to|and|or)\b"
    r"|[.,;:!?]|$)"
)


def _find_column(text: str) -> str:
    """Extract a likely column name from a request.

    Returns the raw word, case-insensitive. Stops at the first
    preposition or punctuation so "by site in Trials" extracts
    "site", not "site in Trials". The tool that receives the result
    resolves it against the actual headers.
    """
    m = re.search(r"\bcolumn\s+" + _COLUMN_TAIL, text, re.I)
    if m:
        return m.group(1).strip()

    m = re.search(r"\b" + _COLUMN_TAIL + r"\s+column\b", text, re.I)
    if m:
        return m.group(1).strip()

    m = re.search(r"\bby\s+" + _COLUMN_TAIL, text, re.I)
    if m:
        return m.group(1).strip()

    return ""

def _singular_to_column(text: str) -> str:
    """Guess the ID column that matches a noun in the request.

    'how many orders'    → 'order ID'
    'how many customers' → 'customer ID'

    Returns "" if no noun is found. The tool that receives it then
    resolves the name against the actual headers, so 'order ID'
    fuzzy-matches 'Order ID', 'order_id', or 'Order_ID'.
    """
    m = re.search(r"\bhow many (\w+?)s?\b", text, re.I)
    if not m:
        return ""
    noun = m.group(1).lower()
    return f"{noun} ID"
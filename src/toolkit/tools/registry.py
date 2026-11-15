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

@dataclass
class ToolResult:
    """What an action tool returns when 'it worked' is not a yes/no.

    Read-only tools keep returning a plain string; tool_said_no()
    classifies those as it always has. Action tools — send, draft,
    archive, book — return a ToolResult so partial success is
    representable. run_direct and run_agent prefer .ok when present
    and fall back to tool_said_no() for bare strings.
    """
    ok: bool
    prose: str


def said_ok(prose: str) -> ToolResult:
    return ToolResult(ok=True, prose=str(prose))


def said_no(prose: str) -> ToolResult:
    return ToolResult(ok=False, prose=str(prose))
# ── the registry ──────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_tools() -> dict[str, Tool]:
    """Build the tool dict once, on first call.

    Importing the modules here (inside the function) rather than at
    module top level avoids a circular import: tools import from
    toolkit.tools.registry for the Tool class, but the registry
    builds the dict by importing the tool modules.
    """
    from toolkit.tools import calendar, data, mail, write  # noqa: F401

    out: dict[str, Tool] = {}
    for module in (calendar, data, mail, write):
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
            r"\b(busiest|quietest|month by month|monthly|by month|"
            r"january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\b",
            t, re.I)),
        tool="group_by_month",
        args=lambda t: {
            "tab": _find_tab(t),
            "date_column": _find_column(t),
            "distinct_column": _singular_to_column(t),
            "summary_only": bool(re.search(r"\b(busiest|quietest)\b", t, re.I)),
            "quietest": bool(re.search(r"\bquietest\b", t, re.I)),
            **_find_month_filter(t),
        },
    ),
    Matcher(
        name="date_range",
        test=lambda t: bool(re.search(
            r"\b(data|date)\s+range\b|"
            r"\b(earliest|latest|first and last|span|how long)\b"
            r".{0,40}\b(date|order|record|entry)\b",
            t, re.I)),
        tool="date_range",
        args=lambda t: {
            "tab": _find_tab(t),
            "column": _find_column(t),
        },
    ),
    Matcher(
        name="summarise_column",
        test=lambda t: bool(
            re.search(
                r"\b(average|mean|median|sum|total|how much|max|maximum|"
                r"min|minimum|highest|lowest)\b",
                t, re.I,
            )
            and not re.search(r"\bby\b", t, re.I)
            and _find_column(t)
        ),
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
            "column": _find_column(t) or _singular_to_column(t),
        },
        soft=True,
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
        soft=True,
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
            r"\b(what can you see|describe (the |this )?(sheet|data|tab)|"
            r"what'?s in (the |this )?(sheet|tab|data)|"
            r"what is in (the |this )?(sheet|tab|data)|"
            r"show me (the )?sheet|what tabs|list (the )?tabs|"
            r"what columns)\b",
            t, re.I)),
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
        name="read_inbox",
        test=lambda t: bool(re.search(
            r"\b(inbox|unread|new emails|check (my )?mail|"
            r"read (my )?mail|any new (mail|messages)|what'?s unread)\b",
            t, re.I)),
        tool="read_inbox",
        args=lambda t: {},
    ),
    Matcher(
        name="archive_thread",
        test=lambda t: bool(re.search(
            r"\barchive\b.{0,30}\b(email|thread|message)\b|"
            r"\b(email|thread|message)\b.{0,30}\barchive\b",
            t, re.I)),
        tool="archive_thread",
        args=lambda t: {
            # Grab the token after 'email' or 'thread' — real Gmail IDs
            # are hex, fake IDs are 'thd_1', both work with \w+.
            "thread_id": (
                (m := re.search(
                    r"\b(?:email|thread|message)\s+([A-Za-z0-9_\-]{3,})",
                    t, re.I))
                and m.group(1) or ""
            ),
        },
        soft=True,
    ),
    Matcher(
        name="search_mail",
        test=lambda t: bool(re.search(
            r"\b(search|find|look for|do i have)\b.{0,30}\b(emails?|mail|messages?)\b",
            t, re.I)),
        tool="search_mail",
        args=lambda t: {
            "query": (
                (m := re.search(r"\b(?:for|about)\s+(.+)$", t, re.I))
                and m.group(1).strip() or t.strip()
            ),
        },
    ),
    Matcher(
        name="send_email",
        test=lambda t: bool(re.search(
            r"\b(send|write|draft)\b.{0,30}\b(email|mail|message)\b.{0,30}\bto\b",
            t, re.I)),
        tool="send_email",
        args=lambda t: {
            "to": (
                (m := re.search(r"\bto\s+([^\s,;]+@[^\s,;]+)", t, re.I))
                and m.group(1) or ""
            ),
            "subject": "",
            "body": "",
        },
        soft=True,
    ),
    Matcher(
        name="agenda",
        test=lambda t: bool(re.search(
            r"\b(calendar|agenda|schedule|events)\b.{0,20}\b(today|tomorrow)\b|"
            r"\b(what'?s|check) (on )?my (calendar|schedule)\b",
            t, re.I)),
        tool="agenda",
        args=lambda t: {
            "when": "tomorrow" if "tomorrow" in t.lower() else "today"
        },
    ),
    Matcher(
        name="book_meeting",
        test=lambda t: bool(re.search(
            r"\b(book|schedule|create|add)\b.{0,20}\b(meeting|event|call)\b",
            t, re.I)),
        tool="book_meeting",
        args=lambda t: {
            # Very basic extraction for the direct matcher. 
            # The LLM handles the complex stuff.
            "title": (re.search(r"\b(?:meeting|event|call)\s+(?:called\s+|about\s+)?['\"]?([^'\"]+)['\"]?", t, re.I).group(1).strip()
                      if re.search(r"\b(?:meeting|event|call)\s+(?:called\s+|about\s+)?['\"]?([^'\"]+)['\"]?", t, re.I) else "Meeting"),
            "when": "today 14:00", 
        },
        soft=True,
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

    tools = load_tools()
    if re.search(
        r"\b(how many|list|show|what)\b.{0,80}\b"
        r"(tools|tasks|capabilities)\b|\bwhat can you do\b",
        text, re.I,
    ):
        descriptions = "; ".join(
            tool.what for _, tool in sorted(tools.items())
        )
        return DirectResult(
            ok=True,
            tool="tool_catalog",
            answer=(
                f"I have access to {len(tools)} tools. "
                f"They let me {descriptions}."
            ),
        )

    _validate_matchers()

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

        # A ToolResult carries its own verdict. A bare string is
        # classified by tool_said_no() as it always has been. This
        # is what lets an action tool say "partly worked" without
        # the prose being misread.
        if isinstance(result, ToolResult):
            text_result = result.prose
            failed = not result.ok
        else:
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
    """Resolve a tab name from the actual sheet schema when possible."""
    from toolkit.adapters.registry import sheet

    tabs = sheet().list_tabs()
    normalised_text = _normalise_phrase(text)
    for name in sorted(tabs, key=len, reverse=True):
        phrase = _normalise_phrase(name)
        if not phrase:
            continue
        match = re.search(
            r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])",
            normalised_text,
        )
        if match:
            before = normalised_text[:match.start()].split()
            after = normalised_text[match.end():].split()
            if (
                (before and before[-1] in {"in", "from", "of", "on", "for"})
                or (after and after[0] in {"tab", "sheet", "worksheet"})
            ):
                return name

    # Preserve explicit unknown tab names so the tool reports them rather
    # than silently answering from the first tab. Generic data nouns are
    # not treated as tab names ("date range of orders", for example).
    m = re.search(
        r"\b(?:in|from|on|of)\s+(?:the\s+)?"
        r"([A-Za-z][\w .\-]{0,40}?)"
        r"(?=\s+\b(?:in|from|of|on|for|by|where|with)\b|[.,;:!?]|$)",
        text, re.I,
    )
    if m:
        candidate = m.group(1).strip()
        candidate_phrase = _normalise_phrase(candidate)
        month_names = "|".join(_MONTHS)
        is_month_filter = bool(re.fullmatch(
            rf"(?:{month_names})(?: (?:19|20)\d{{2}})?",
            candidate_phrase,
        ))
        if candidate_phrase not in {
            "data", "dataset", "order", "orders", "record", "records",
            "entry", "entries", "transaction", "transactions",
        } and not is_month_filter:
            return candidate
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
    """Resolve a named header from the request, then use phrasing clues.

    Returns the raw word, case-insensitive. Stops at the first
    preposition or punctuation so "by site in Trials" extracts
    "site", not "site in Trials".
    """
    from toolkit.adapters.registry import sheet

    adapter = sheet()
    tab_name = _find_tab(text)
    tabs = [tab_name] if tab_name else adapter.list_tabs()
    normalised_text = _normalise_phrase(text)
    matches: list[tuple[int, str]] = []
    for name in tabs:
        headers = adapter.read_tab(name, sample=1).headers
        for header in headers:
            phrase = _normalise_phrase(header)
            if phrase and re.search(
                r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])",
                normalised_text,
            ):
                matches.append((len(phrase), header))
    if matches:
        return max(matches, key=lambda match: match[0])[1]

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


def _normalise_phrase(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _find_month_filter(text: str) -> dict[str, int]:
    month_pattern = "|".join(_MONTHS)
    match = re.search(r"\b(" + month_pattern + r")\b", text, re.I)
    if not match:
        return {}

    result = {"month": _MONTHS[match.group(1).lower()]}
    year = re.search(r"\b(?:19|20)\d{2}\b", text)
    if year:
        result["year"] = int(year.group())
    return result


def _singular_to_column(text: str) -> str:
    """Guess the ID column that matches a noun in the request.

    'how many orders'    → 'order ID'
    'how many customers' → 'customer ID'

    Returns "" if no noun is found. The tool that receives it then
    resolves the name against the actual headers, so 'order ID'
    fuzzy-matches 'Order ID', 'order_id', or 'Order_ID'.
    """
    m = re.search(
        r"\b(?:how many(?:\s+(?:unique|distinct|different))?|"
        r"(?:count|number of)\s+(?:the\s+)?"
        r"(?:unique|distinct|different))\s+(\w+?)s?\b",
        text,
        re.I,
    )
    if not m:
        return ""
    noun = m.group(1).lower()
    return f"{noun} ID"
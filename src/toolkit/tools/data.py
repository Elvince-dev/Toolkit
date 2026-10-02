"""Data tools — read, count, describe, find patterns.

Ported from Code.gs. The signatures are the same (a dict in, a
string out). What changed:

  * They call `registry.sheet()` for the adapter instead of
    SpreadsheetApp.
  * They receive a TabData and pass it to `brain.analysis` functions
    rather than reading columns themselves.
  * Every one of them returns a human sentence. Never a dict, never
    a JSON blob. The agent loop expects prose it can quote.
"""

from __future__ import annotations

from typing import Any

from toolkit.adapters.registry import sheet
from toolkit.brain.analysis import (
    compare_groups,
    find_outliers,
    one_thing_carrying_it,
    too_small_to_judge,
    trend_over,
)
from toolkit.brain.parsing import read_date, read_number
from toolkit.tools.registry import Tool


TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    TOOLS[tool.name] = tool


# ── tab-level ─────────────────────────────────────────────────────────

def _describe_sheet(_: dict[str, Any]) -> str:
    """What tabs exist, how big they are, what columns they hold.

    Reads every tab in full to get a true row count, then shows
    headers. This is the tool someone runs first, so the counts must
    be exact — "5 rows" when the tab has 8 is a lie.

    Column names are shown in full up to the first six, then a count
    of the remainder. No mid-word truncation.
    """
    adapter = sheet()
    tabs = adapter.list_tabs()
    if not tabs:
        return "There are no tabs yet. The CSV folder is empty."

    lines = [f"{len(tabs)} tab{'s' if len(tabs) != 1 else ''}:"]
    for name in tabs:
        try:
            # Sample 1 million — the whole file, for an exact count.
            tab = adapter.read_tab(name, sample=1_000_000)
        except Exception as exc:
            lines.append(f"  · {name}: could not read ({exc})")
            continue
        shown = tab.headers[:6]
        cols = ", ".join(shown) or "(no headers)"
        remaining = len(tab.headers) - len(shown)
        if remaining > 0:
            cols += f", +{remaining} more"
        lines.append(
            f"  · {name}: {tab.row_count} rows, "
            f"{tab.column_count} columns — {cols}"
        )
    return "\n".join(lines)


def _count_rows(_: dict[str, Any]) -> str:
    """How many rows of data, per tab, exactly."""
    adapter = sheet()
    tabs = adapter.list_tabs()
    if not tabs:
        return "There are no tabs yet."

    total = 0
    lines = []
    for name in tabs:
        try:
            # A high sample cap gets the true count without loading
            # the whole file twice.
            tab = adapter.read_tab(name, sample=1_000_000)
        except Exception as exc:
            lines.append(f"  · {name}: could not read ({exc})")
            continue
        total += tab.row_count
        lines.append(f"  · {name}: {tab.row_count} rows")
    header = (
        f"{len(tabs)} tab{'s' if len(tabs) != 1 else ''}, "
        f"{total} row{'s' if total != 1 else ''} of data altogether:"
    )
    return header + "\n" + "\n".join(lines)


def _count_rows_in(args: dict[str, Any]) -> str:
    """How many rows in one specific tab."""
    name = str(args.get("tab") or "").strip()
    adapter = sheet()

    if not name:
        return _count_rows({})

    try:
        tab = adapter.read_tab(name, sample=1_000_000)
    except FileNotFoundError:
        return (
            f"There is no tab called {name!r}. "
            f"I have: {', '.join(adapter.list_tabs()) or 'none'}"
        )
    except Exception as exc:
        return f"I could not read {name!r}: {exc}"

    n = tab.row_count
    return (
        f"{name!r} has {n} row{'s' if n != 1 else ''} of data "
        f"across {tab.column_count} column"
        f"{'s' if tab.column_count != 1 else ''}."
    )


# ── column-level ──────────────────────────────────────────────────────

def _compare_groups(args: dict[str, Any]) -> str:
    """Count the rows in each group. Optionally average a number."""
    tab, err = _get_tab(args)
    if err:
        return err

    column = str(args.get("column") or "").strip()
    if not column:
        guess = _guess_group_column(tab.headers)
        if not guess:
            return (
                f"I could not tell which column to group by in "
                f"{tab.name!r}. Columns available: "
                f"{', '.join(tab.headers[:10])}"
            )
        column = guess

    value_column = str(args.get("value") or "").strip() or None

    try:
        report = compare_groups(tab, column, value_column)
    except KeyError as exc:
        return str(exc)

    if report.total == 0:
        return f"{tab.name!r} has no rows in {column!r}."

    lines = [
        f"{report.total} rows in {tab.name!r}, by {column!r}:",
    ]
    for g in report.groups[:15]:
        avg = f", avg {g.average}" if g.average is not None else ""
        lines.append(f"  · {g.name}: {g.count} ({g.share}%){avg}")

    if len(report.groups) > 15:
        lines.append(f"  … and {len(report.groups) - 15} more")

    if report.notes:
        lines.append("")
        lines.extend(report.notes)

    concentration = one_thing_carrying_it(report)
    if concentration:
        lines.append("")
        lines.append(concentration.say)

    small = too_small_to_judge(report)
    if small:
        lines.append(small.say)

    return "\n".join(lines)


def _find_outliers(args: dict[str, Any]) -> str:
    """Find rows well outside the normal range for a numeric column."""
    tab, err = _get_tab(args)
    if err:
        return err

    column = str(args.get("column") or "").strip()
    if not column:
        guess = _guess_numeric_column(tab)
        if not guess:
            return (
                f"I could not tell which column to check in {tab.name!r}. "
                f"I need a numeric one — I can see: "
                f"{', '.join(tab.headers[:10])}"
            )
        column = guess

    try:
        report = find_outliers(tab, column)
    except KeyError as exc:
        return str(exc)

    if report.counted < 4:
        return (
            f"{column!r} in {tab.name!r} only has {report.counted} "
            f"number{'s' if report.counted != 1 else ''} — too few "
            f"to judge what is unusual."
        )

    lines = [
        f"Column {column!r} in {tab.name!r}:",
        f"  {report.counted} numbers, median {report.median:g}, "
        f"normal range {report.normal_from:g} to {report.normal_to:g}",
    ]

    if not report.total:
        lines.append("Nothing is unusual.")
        return "\n".join(lines)

    if report.high:
        vals = ", ".join(f"row {o.row} ({o.value:g})" for o in report.high[:6])
        lines.append(f"  Unusually high: {vals}")
    if report.low:
        vals = ", ".join(f"row {o.row} ({o.value:g})" for o in report.low[:6])
        lines.append(f"  Unusually low: {vals}")

    return "\n".join(lines)


def _trend_over(args: dict[str, Any]) -> str:
    """Is it rising, falling, or steady?"""
    tab, err = _get_tab(args)
    if err:
        return err

    date_col = str(args.get("date_column") or args.get("date") or "").strip()
    value_col = str(args.get("value_column") or args.get("value") or "").strip() or None

    if not date_col:
        guess = _guess_date_column(tab)
        if not guess:
            return (
                f"I could not find a date column in {tab.name!r} to "
                f"trend over. Columns: {', '.join(tab.headers[:10])}"
            )
        date_col = guess

    try:
        report = trend_over(tab, date_col, value_col)
    except (KeyError, ValueError) as exc:
        return str(exc)

    return report.note


# ── helpers ───────────────────────────────────────────────────────────

def _get_tab(args: dict[str, Any]):
    """Load a tab by name, or the first tab if name is blank.

    Returns (TabData, error_string). Exactly one of the two is None.
    """
    adapter = sheet()
    name = str(args.get("tab") or "").strip()

    if not name:
        tabs = adapter.list_tabs()
        if not tabs:
            return None, "There are no tabs yet."
        name = tabs[0]

    try:
        return adapter.read_tab(name, sample=5000), None
    except FileNotFoundError:
        return None, (
            f"There is no tab called {name!r}. "
            f"I have: {', '.join(adapter.list_tabs()) or 'none'}"
        )
    except Exception as exc:
        return None, f"I could not read {name!r}: {exc}"


def _guess_group_column(headers: list[str]) -> str | None:
    """A column that looks like a category."""
    hints = (
        "region", "category", "type", "status", "group", "class",
        "branch", "department", "team", "segment", "kind", "stage",
        "channel", "source", "priority",
    )
    for h in headers:
        hl = h.lower()
        for hint in hints:
            if hint in hl:
                return h
    # Fall back to the first text-looking header
    return headers[0] if headers else None


def _guess_numeric_column(tab) -> str | None:
    """A column where most cells parse as numbers."""
    for h in tab.headers:
        values = tab.column(h)
        nums = sum(1 for v in values if read_number(v) is not None)
        if values and nums >= len(values) * 0.7:
            return h
    return None


def _guess_date_column(tab) -> str | None:
    """A column where most cells parse as dates."""
    hints = ("date", "when", "created", "updated", "time", "day")
    for h in tab.headers:
        if any(hint in h.lower() for hint in hints):
            return h
    # Fall back to sniffing the values
    for h in tab.headers:
        values = tab.column(h)
        dates = sum(1 for v in values if read_date(v) is not None)
        if values and dates >= len(values) * 0.7:
            return h
    return None


# ── register ──────────────────────────────────────────────────────────

register(Tool(
    name="describe_sheet",
    what="list every tab and what is in it",
    need=(),
    run=_describe_sheet,
))

register(Tool(
    name="count_rows",
    what="count the rows in every tab",
    need=(),
    run=_count_rows,
))

register(Tool(
    name="count_rows_in",
    what="count the rows in one tab",
    need=(),
    run=_count_rows_in,
))

register(Tool(
    name="compare_groups",
    what="count the rows in each group, biggest first",
    need=(),
    run=_compare_groups,
))

register(Tool(
    name="find_outliers",
    what="find rows well outside the normal range",
    need=(),
    run=_find_outliers,
))

register(Tool(
    name="trend_over",
    what="see whether something is rising or falling",
    need=(),
    run=_trend_over,
))
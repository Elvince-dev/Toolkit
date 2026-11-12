"""Data tools — read, count, describe, find patterns.

Ported from Code.gs. The signatures are the same (a dict in, a
string out). What changed:

  * They call `registry.sheet()` for the adapter instead of
    SpreadsheetApp.
  * They receive a TabData and pass it to `brain.analysis` functions
    rather than reading columns themselves.
  * Every one of them returns a human sentence. Never a dict, never
    a JSON blob. The agent loop expects prose it can quote.
  * Column guessing uses the active domain profile (brain/domain.py)
    instead of hardcoded word lists.
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
from statistics import median as _median


TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    TOOLS[tool.name] = tool


# ── tab-level ─────────────────────────────────────────────────────────

def _describe_sheet(_: dict[str, Any]) -> str:
    """What tabs exist, how big they are, what columns they hold.

    Reads every tab in full to get a true row count, then shows
    headers. Column names are shown in full up to the first six,
    then a count of the remainder.
    """
    adapter = sheet()
    tabs = adapter.list_tabs()
    if not tabs:
        return "There are no tabs yet. The CSV folder is empty."

    lines = [f"{len(tabs)} tab{'s' if len(tabs) != 1 else ''}:"]
    for name in tabs:
        try:
            tab = adapter.read_tab(name, sample=1_000_000)
        except Exception as exc:
            lines.append(f"  · {name}: could not read ({exc})")
            continue
        # show every column. The model needs to see the whole schema
        # to know what it can ask about.
        cols = ", ".join(tab.headers) if tab.headers else "(no headers)"
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

    wanted_col = str(args.get("column") or "").strip()

    # If a column was named and the current tab does not have it,
    # try the other tabs. This is what makes "count the rows by site"
    # find Trials even when the default tab is something else.
    tab = _hop_to_tab_with_column(tab, wanted_col)

    column = _resolve_column(tab, wanted_col)
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
    if value_column:
        value_column = _resolve_column(tab, value_column) or value_column

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

    wanted_col = str(args.get("column") or "").strip()
    tab = _hop_to_tab_with_column(tab, wanted_col)

    column = _resolve_column(tab, wanted_col)
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
        f"  {report.counted} numbers, median {report.median:,.2f}, "
        f"normal range {report.normal_from:,.2f} to {report.normal_to:,.2f}",
    ]

    if not report.total:
        lines.append("Nothing is unusual.")
        return "\n".join(lines)

    if report.high:
        vals = ", ".join(f"row {o.row} ({o.value:,.2f})" for o in report.high[:6])
        lines.append(f"  Unusually high: {vals}")
    if report.low:
        vals = ", ".join(f"row {o.row} ({o.value:,.2f})" for o in report.low[:6])
        lines.append(f"  Unusually low: {vals}")

    return "\n".join(lines)


def _trend_over(args: dict[str, Any]) -> str:
    """Is it rising, falling, or steady?"""
    tab, err = _get_tab(args)
    if err:
        return err

    wanted_date = str(
        args.get("date_column") or args.get("date") or ""
    ).strip()
    wanted_value = str(
        args.get("value_column") or args.get("value") or ""
    ).strip() or None

    tab = _hop_to_tab_with_column(tab, wanted_date)

    date_col = _resolve_column(tab, wanted_date)
    if not date_col:
        guess = _guess_date_column(tab)
        if not guess:
            return (
                f"I could not find a date column in {tab.name!r} to "
                f"trend over. Columns: {', '.join(tab.headers[:10])}"
            )
        date_col = guess

    if wanted_value:
        wanted_value = _resolve_column(tab, wanted_value) or wanted_value

    try:
        report = trend_over(tab, date_col, wanted_value)
    except (KeyError, ValueError) as exc:
        return str(exc)

    return report.note


def _summarise_column(args: dict[str, Any]) -> str:
    """Sum, average, min, max, and count for a numeric column.

    Use this when the user asks for the average, total, sum, min, or
    max of a measure. It computes them all at once because a person
    asking about the "average" almost always wants the range too.
    """
    tab, err = _get_tab(args)
    if err:
        return err

    wanted_col = str(args.get("column") or "").strip()
    tab = _hop_to_tab_with_column(tab, wanted_col)

    column = _resolve_column(tab, wanted_col)
    if not column:
        column = _guess_numeric_column(tab)
    if not column:
        return (
            f"I could not find a numeric column to summarise in "
            f"{tab.name!r}. Columns: {', '.join(tab.headers[:10])}"
        )

    values = tab.column(column)
    nums: list[float] = []
    for v in values:
        n = read_number(v)
        if n is not None:
            nums.append(n)

    if not nums:
        return f"{column!r} in {tab.name!r} has no numbers to summarise."

    total = sum(nums)
    avg = total / len(nums)
    med = _median(nums)
    return (
        f"{column!r} in {tab.name!r}:\n"
        f"  count: {len(nums)}\n"
        f"  sum: {total:,.2f}\n"
        f"  average: {avg:,.2f}\n"
        f"  median: {med:,.2f}\n"
        f"  min: {min(nums):,.2f}\n"
        f"  max: {max(nums):,.2f}"
    )


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
        return adapter.read_tab(name, sample=10_000), None
    except FileNotFoundError:
        return None, (
            f"There is no tab called {name!r}. "
            f"I have: {', '.join(adapter.list_tabs()) or 'none'}"
        )
    except Exception as exc:
        return None, f"I could not read {name!r}: {exc}"


def _resolve_column(tab, wanted: str) -> str:
    """Find the actual header that best matches `wanted`.

    Handles case, spaces vs underscores, and substring matches.
    Returns "" if nothing plausible.
    """
    if not wanted:
        return ""
    w = wanted.strip().lower().replace("_", " ").replace("-", " ")
    # Exact match first
    for h in tab.headers:
        if h.strip().lower().replace("_", " ") == w:
            return h
    # Substring, either direction
    for h in tab.headers:
        hl = h.strip().lower().replace("_", " ")
        if w in hl or hl in w:
            return h
    return ""


def _hop_to_tab_with_column(tab, wanted_col: str):
    """If `wanted_col` is named and not in this tab, try other tabs.

    Only used when the caller did NOT explicitly name a tab. If they
    did name a tab, we respect their choice even if the column is
    missing — that is a real error worth reporting.
    """
    if not wanted_col:
        return tab
    if _resolve_column(tab, wanted_col):
        return tab

    adapter = sheet()
    for name in adapter.list_tabs():
        if name == tab.name:
            continue
        try:
            other = adapter.read_tab(name, sample=10_000)
        except Exception:
            continue
        if _resolve_column(other, wanted_col):
            return other
    return tab


def _guess_group_column(headers: list[str]) -> str | None:
    """A column that looks like a category, using the active domain."""
    from toolkit.brain.domain import domain

    for h in headers:
        if domain().matches("group", h):
            return h
    # Fall back to the first header — better than nothing
    return headers[0] if headers else None


def _guess_numeric_column(tab) -> str | None:
    """A column where most cells parse as numbers.

    The domain tells us what typically holds numbers (amount, price,
    count), but we always trust the data over the vocabulary: if the
    column named "amount" turns out to hold text, we skip it.
    """
    from toolkit.brain.domain import domain

    # First pass: prefer columns whose names match the domain
    for h in tab.headers:
        if not domain().matches("measure", h):
            continue
        values = tab.column(h)
        nums = sum(1 for v in values if read_number(v) is not None)
        if values and nums >= len(values) * 0.7:
            return h

    # Second pass: any column that holds mostly numbers
    for h in tab.headers:
        values = tab.column(h)
        nums = sum(1 for v in values if read_number(v) is not None)
        if values and nums >= len(values) * 0.7:
            return h

    return None


def _guess_date_column(tab) -> str | None:
    """A column that looks like a date, using the active domain."""
    from toolkit.brain.domain import domain

    # First pass: name-based guess
    for h in tab.headers:
        if domain().matches("date", h):
            return h

    # Second pass: value-based sniffing
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

register(Tool(
    name="summarise_column",
    what="sum, average, min, max for a numeric column",
    need=(),
    run=_summarise_column,
))
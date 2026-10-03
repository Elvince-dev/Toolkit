"""Write tools — the mutating half of the toolkit.

Every tool in here takes a snapshot before it writes. That is the
undo guarantee. If a write fails partway, the snapshot is still
valid.

The tools are organised by how destructive they are:

  * **Safe** — append_row, write_cell. Local, small, snapshot is
    cheap. No confirmation needed.
  * **Wide** — fill_column, clean_column. Affects many rows, may
    partially complete. Report exactly what was done.
  * **Risky** — delete_tab, apply_plan. Refuse without explicit
    confirmation, matching the original's RISKY registry.

Nothing here does confirmation itself. The tools describe what they
*would* do; `apply_write` executes after the agent or user has
confirmed. This is the same pattern Code.gs used with propose_action
and confirm_action.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from toolkit.adapters.registry import sheet
from toolkit.brain import snapshot as snap_mod
from toolkit.brain.parsing import read_number
from toolkit.tools.registry import Tool


TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    TOOLS[tool.name] = tool


# ── pending writes ────────────────────────────────────────────────────
#
# A "pending write" is a plan that has been described but not yet
# executed. It lives in memory for the duration of the process. The
# agent uses this to say "here is what I would do, say yes" without
# actually doing it.

_PENDING: dict[str, dict[str, Any]] = {}
PENDING_TTL_SECONDS = 600


def _propose(kind: str, **kwargs: Any) -> str:
    """Register a pending action and return its id."""
    _prune_pending()
    pid = "p-" + uuid.uuid4().hex[:8]
    _PENDING[pid] = {
        "kind": kind,
        "created_at": time.time(),
        **kwargs,
    }
    return pid


def _prune_pending() -> None:
    now = time.time()
    stale = [
        pid for pid, action in _PENDING.items()
        if now - action["created_at"] > PENDING_TTL_SECONDS
    ]
    for pid in stale:
        _PENDING.pop(pid, None)


def pending_by_id(pid: str) -> dict[str, Any] | None:
    _prune_pending()
    return _PENDING.get(pid)


def consume_pending(pid: str) -> dict[str, Any] | None:
    _prune_pending()
    return _PENDING.pop(pid, None)


# ── write_cell ────────────────────────────────────────────────────────

def _write_cell(args: dict[str, Any]) -> str:
    """Write one value into one cell.

    A1 must be a specific cell like "B4", not a range. The tab must
    already exist and have a header row.

    Small, focused, cheap to snapshot. No confirmation needed.
    """
    tab = str(args.get("tab") or "").strip()
    a1 = str(args.get("a1") or "").strip().upper()
    value = args.get("value", "")

    if not tab:
        return "Which tab? Give me a name like 'Sales'."
    if not a1 or not _looks_like_cell(a1):
        return (
            f"{a1!r} is not a cell reference. I need something like "
            f"'B4', not a range."
        )

    adapter = sheet()
    try:
        data = adapter.read_tab(tab, sample=1)
    except FileNotFoundError:
        return (
            f"There is no tab called {tab!r}. "
            f"I have: {', '.join(adapter.list_tabs()) or 'none'}"
        )

    # Parse the A1 into row and column
    from toolkit.adapters.sheets.sqlite import _parse_a1  # reuse
    row, col = _parse_a1(a1)

    if row == 0:
        # Writing into the header row. That is fine, but we need to
        # read the full table to be sure of the width.
        try:
            data = adapter.read_tab(tab, sample=0)
        except Exception as exc:
            return f"I could not read {tab!r}: {exc}"

    if col >= len(data.headers) and not data.headers:
        return (
            f"{tab!r} has no columns yet. Write a full table first "
            f"with 'write the rows'."
        )

    snap = snap_mod.take(tab, note=f"write_cell {a1}")

    # Read the full table, modify the cell, write back
    try:
        full = adapter.read_tab(tab, sample=0)
    except Exception as exc:
        return f"I could not read {tab!r} after snapshotting: {exc}"

    headers = list(full.headers)
    rows = [list(r) for r in full.rows]

    # Pad columns if the write is to a new one
    while len(headers) <= col:
        headers.append(f"Column {len(headers) + 1}")
    for r in rows:
        while len(r) < len(headers):
            r.append("")

    # Sheet row 1 is the header; data row 0 is sheet row 2.
    # If the target is sheet row 1, we are editing the header itself.
    if row == 0:
        # Pad the header row's columns and write into it directly
        while len(headers) <= col:
            headers.append(f"Column {len(headers) + 1}")
        headers[col] = str(value)
    else:
        data_row = row - 1
        # Pad data rows if the write is below the bottom
        while len(rows) <= data_row:
            rows.append(["" for _ in headers])
        rows[data_row][col] = str(value)

    try:
        adapter.write_range(tab, "A1", [headers] + rows)
    except Exception as exc:
        return (
            f"The write failed: {exc}\n\n"
            f"Snapshot {snap.id} is intact. Say 'undo' to restore."
        )

    return (
        f"Wrote {value!r} to {tab}!{a1}.\n"
        f"Snapshot {snap.id} taken first — say 'undo' to reverse."
    )


def _looks_like_cell(a1: str) -> bool:
    import re
    return bool(re.fullmatch(r"[A-Z]{1,3}\d{1,7}", a1))


# ── append_row ────────────────────────────────────────────────────────

def _append_row(args: dict[str, Any]) -> str:
    """Append one row of values to a tab.

    Values are positional: the first goes in the first column, the
    second in the second, and so on. If fewer values are given than
    there are columns, the rest are filled with empty strings.
    """
    tab = str(args.get("tab") or "").strip()
    values = args.get("values")

    if not tab:
        return "Which tab? Give me a name like 'Sales'."

    if isinstance(values, str):
        # Split a comma-separated string
        values = [v.strip() for v in values.split(",")]
    elif not isinstance(values, list):
        return (
            "I need values to append. Give them as a list, or as a "
            "comma-separated string."
        )

    adapter = sheet()
    try:
        data = adapter.read_tab(tab, sample=1)
    except FileNotFoundError:
        return (
            f"There is no tab called {tab!r}. "
            f"I have: {', '.join(adapter.list_tabs()) or 'none'}"
        )

    if not data.headers:
        return (
            f"{tab!r} has no columns yet. Write a full table first "
            f"with 'write the rows'."
        )

    snap = snap_mod.take(tab, note=f"append_row to {tab}")

    try:
        adapter.append_rows(tab, [[str(v) for v in values]])
    except Exception as exc:
        return (
            f"The append failed: {exc}\n\n"
            f"Snapshot {snap.id} is intact. Say 'undo' to restore."
        )

    n = len(values)
    return (
        f"Appended {n} value{'s' if n != 1 else ''} to {tab!r}.\n"
        f"Snapshot {snap.id} taken first — say 'undo' to reverse."
    )


# ── fill_column ───────────────────────────────────────────────────────

def _fill_column(args: dict[str, Any]) -> str:
    """Fill a column with a computed or literal value.

    Unlike the AI-driven `fill_column` in Code.gs, this one takes a
    literal value or a simple formula:

        value="x"           → every cell becomes "x"
        value="@upper"      → every cell is upper-cased
        value="@trim"       → every cell is trimmed
        value="@from:A"     → copy from column A (same row)
        value="@now"        → today's date as YYYY-MM-DD

    For AI-driven fills, we will add a separate tool later. This one
    is the fast, deterministic, snapshot-safe version.
    """
    tab = str(args.get("tab") or "").strip()
    column = str(args.get("column") or "").strip().upper()
    value = str(args.get("value") or "")
    first = int(args.get("first") or 2)
    last = int(args.get("last") or 0)

    if not tab:
        return "Which tab?"
    if not column or not column.isalpha() or len(column) > 3:
        return f"{column!r} is not a column letter."

    adapter = sheet()
    try:
        data = adapter.read_tab(tab, sample=0)
    except FileNotFoundError:
        return (
            f"There is no tab called {tab!r}. "
            f"I have: {', '.join(adapter.list_tabs()) or 'none'}"
        )

    from toolkit.adapters.sheets.sqlite import _parse_a1
    _, col_index = _parse_a1(column + "1")

    if col_index >= len(data.headers):
        return (
            f"{tab!r} has no column {column!r}. It has: "
            f"{', '.join(data.headers)}"
        )

    total = len(data.rows)
    if last <= 0 or last > total + 1:
        last = total + 1

    snap = snap_mod.take(tab, note=f"fill_column {column} in {tab}")

    headers = list(data.headers)
    rows = [list(r) for r in data.rows]
    source_col: int | None = None

    for i in range(first - 2, min(last - 1, len(rows))):
        # i is 0-based row index into data rows. Sheet row `first` = data row 0.
        target_row = i
        if target_row >= len(rows):
            break

        if value.startswith("@from:"):
            src = value[6:].strip().upper()
            if source_col is None:
                _, source_col = _parse_a1(src + "1")
            new = str(rows[target_row][source_col]) if source_col < len(rows[target_row]) else ""
        elif value == "@upper":
            new = str(rows[target_row][col_index]).upper()
        elif value == "@lower":
            new = str(rows[target_row][col_index]).lower()
        elif value == "@trim":
            new = str(rows[target_row][col_index]).strip()
        elif value == "@now":
            new = time.strftime("%Y-%m-%d")
        else:
            new = value

        while len(rows[target_row]) <= col_index:
            rows[target_row].append("")
        rows[target_row][col_index] = new

    try:
        adapter.write_range(tab, "A1", [headers] + rows)
    except Exception as exc:
        return (
            f"The fill failed: {exc}\n\n"
            f"Snapshot {snap.id} is intact. Say 'undo' to restore."
        )

    filled = max(0, min(last - 1, len(rows)) - (first - 2))
    return (
        f"Filled column {column} in {tab!r}, rows {first} to {last - 1} "
        f"({filled} rows).\n"
        f"Snapshot {snap.id} taken first — say 'undo' to reverse."
    )


# ── clean_column ──────────────────────────────────────────────────────

def _clean_column(args: dict[str, Any]) -> str:
    """Trim whitespace and collapse casing variants in a column.

    Two operations, safe on any string column:

      * Strip leading and trailing whitespace from every value.
      * Collapse values that differ only in case to the most common
        spelling (e.g. "Thika", "thika", "THIKA" → "Thika").

    Does not touch numbers or dates. Does not delete rows.
    """
    tab = str(args.get("tab") or "").strip()
    column = str(args.get("column") or "").strip()

    if not tab:
        return "Which tab?"
    if not column:
        return "Which column? Give me a name or a letter."

    adapter = sheet()
    try:
        data = adapter.read_tab(tab, sample=0)
    except FileNotFoundError:
        return (
            f"There is no tab called {tab!r}. "
            f"I have: {', '.join(adapter.list_tabs()) or 'none'}"
        )

    try:
        col_index = data.column_index(column)
    except KeyError as exc:
        return str(exc)

    snap = snap_mod.take(tab, note=f"clean_column {column} in {tab}")

    headers = list(data.headers)
    rows = [list(r) for r in data.rows]

    # First: trim and gather case-collapsed groups
    trimmed = 0
    for r in rows:
        while len(r) <= col_index:
            r.append("")
        original = str(r[col_index])
        stripped = original.strip()
        if stripped != original:
            trimmed += 1
        r[col_index] = stripped

    # Second: find the most common casing for each lowercase form
    counts: dict[str, dict[str, int]] = {}
    for r in rows:
        v = str(r[col_index])
        if not v:
            continue
        low = v.lower()
        counts.setdefault(low, {})
        counts[low][v] = counts[low].get(v, 0) + 1

    canonical: dict[str, str] = {}
    for low, variants in counts.items():
        if len(variants) > 1:
            # Pick the most frequent spelling. Ties go to title-case.
            best = max(
                variants.items(),
                key=lambda kv: (kv[1], kv[0] == kv[0].title()),
            )[0]
            canonical[low] = best

    merged = 0
    for r in rows:
        v = str(r[col_index])
        if not v:
            continue
        low = v.lower()
        if low in canonical and canonical[low] != v:
            r[col_index] = canonical[low]
            merged += 1

    if trimmed == 0 and merged == 0:
        return (
            f"Column {column!r} in {tab!r} is already clean — no "
            f"leading or trailing whitespace, no casing variants."
        )

    try:
        adapter.write_range(tab, "A1", [headers] + rows)
    except Exception as exc:
        return (
            f"The clean failed: {exc}\n\n"
            f"Snapshot {snap.id} is intact. Say 'undo' to restore."
        )

    parts = []
    if trimmed:
        parts.append(f"trimmed {trimmed} value{'s' if trimmed != 1 else ''}")
    if merged:
        parts.append(
            f"merged {merged} casing variant{'s' if merged != 1 else ''}"
        )
    return (
        f"Cleaned column {column!r} in {tab!r}: {'; '.join(parts)}.\n"
        f"Snapshot {snap.id} taken first — say 'undo' to reverse."
    )


# ── delete_tab ────────────────────────────────────────────────────────

def _delete_tab(args: dict[str, Any]) -> str:
    """Delete an entire tab.

    Destructive. Refuses unless confirm=True is passed.
    """
    tab = str(args.get("tab") or "").strip()
    confirm = bool(args.get("confirm"))

    if not tab:
        return "Which tab should I delete?"

    adapter = sheet()
    if tab not in adapter.list_tabs():
        return (
            f"There is no tab called {tab!r}. "
            f"I have: {', '.join(adapter.list_tabs()) or 'none'}"
        )

    if not confirm:
        snap = snap_mod.take(tab, note=f"before deleting {tab}")
        return (
            f"Deleting {tab!r} is not reversible from the adapter "
            f"side — the whole file or table goes away.\n"
            f"I have taken snapshot {snap.id} first.\n\n"
            f"Say 'yes, delete {tab}' to proceed, or 'undo' to "
            f"restore."
        )

    snap = snap_mod.take(tab, note=f"before deleting {tab}")
    try:
        adapter.delete_tab(tab)
    except Exception as exc:
        return (
            f"Delete failed: {exc}\n\n"
            f"Snapshot {snap.id} is intact."
        )

    return (
        f"Deleted tab {tab!r}.\n"
        f"Snapshot {snap.id} holds the {snap.row_count}-row table. "
        f"Say 'undo' to restore it."
    )


# ── undo_last ─────────────────────────────────────────────────────────

def _undo_last(args: dict[str, Any]) -> str:
    """Restore a tab from the most recent (un-undone) snapshot."""
    tab = str(args.get("tab") or "").strip() or None

    snap = snap_mod.latest(tab)
    if snap is None:
        return (
            "No snapshots to undo. (Every write takes one, so this "
            "means nothing has been written yet in this session.)"
        )

    result = snap_mod.restore(snap.id)
    if result["ok"]:
        return result["say"]
    return result["why"]


# ── list_snapshots ────────────────────────────────────────────────────

def _list_snapshots(args: dict[str, Any]) -> str:
    """Show what snapshots exist for undo."""
    tab = str(args.get("tab") or "").strip() or None
    return snap_mod.list_say(tab)


# ── register ──────────────────────────────────────────────────────────

register(Tool(
    name="write_cell",
    what="write one value into one cell",
    need=("tab", "a1"),
    run=_write_cell,
))

register(Tool(
    name="append_row",
    what="append one row of values to a tab",
    need=("tab", "values"),
    run=_append_row,
))

register(Tool(
    name="fill_column",
    what="fill a column with a value, or @upper/@lower/@trim/@now/@from",
    need=("tab", "column", "value"),
    run=_fill_column,
))

register(Tool(
    name="clean_column",
    what="trim whitespace and merge casing variants in a column",
    need=("tab", "column"),
    run=_clean_column,
))

register(Tool(
    name="delete_tab",
    what="delete an entire tab (needs confirm=True)",
    need=("tab",),
    run=_delete_tab,
))

register(Tool(
    name="undo_last",
    what="restore a tab from the most recent snapshot",
    need=(),
    run=_undo_last,
))

register(Tool(
    name="list_snapshots",
    what="show what snapshots exist for undo",
    need=(),
    run=_list_snapshots,
))
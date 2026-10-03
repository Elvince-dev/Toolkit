"""Snapshots — the undo layer.

Every mutating tool takes a snapshot of the affected table before it
writes. The snapshot is stored in a separate SQLite file so a corrupt
primary database cannot take the snapshots with it.

Design choices, and why:

  * **Whole table, not range.** The original Code.gs snapshotted only
    the range being written. This adapter snapshots the whole table.
    Tradeoff: more disk per snapshot, but it means "undo" is one call
    that cannot go wrong. On a 10,000-row table this is ~2MB — cheap.
  * **Snapshots expire.** A snapshot older than the newest 20 is
    deleted on the next snapshot. Bounded disk usage without needing
    a maintenance command.
  * **Snapshot before, not after.** If the write fails partway, the
    snapshot is still valid — the table is in the pre-write state
    for the rows that were already written.
  * **Ids are short and human-readable.** `s-2026-10-04-1a2b` — you
    can type it in the CLI without copy-paste.

The snapshot store is deliberately a **separate SQLite file** from the
main data. Reason: if the user points the toolkit at a real database
(Postgres, MySQL), the toolkit should still be able to offer undo
without writing to that database.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from toolkit.adapters.registry import sheet
from toolkit.config import settings


MAX_SNAPSHOTS = 20


_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          TEXT PRIMARY KEY,
    tab         TEXT NOT NULL,
    taken_at    REAL NOT NULL,
    headers     TEXT NOT NULL,
    rows        TEXT NOT NULL,
    row_count   INTEGER NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    undone      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_snapshots_taken ON snapshots(taken_at);
"""


@dataclass
class Snapshot:
    """One saved state of a tab, from which we can restore."""

    id: str
    tab: str
    taken_at: float
    headers: list[str]
    rows: list[list[Any]]
    note: str
    undone: bool = False

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def when(self) -> str:
        """A human phrase for the age: 'just now', '5 min ago'."""
        secs = int(time.time() - self.taken_at)
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60} min ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"


# ── storage ───────────────────────────────────────────────────────────

def _path() -> Path:
    p = settings().data_dir / "snapshots.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(_path()))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _new_id() -> str:
    """'s-2026-10-04-1a2b' — sortable by date, short enough to type."""
    stamp = time.strftime("%Y-%m-%d")
    suffix = uuid.uuid4().hex[:4]
    return f"s-{stamp}-{suffix}"


# ── public API ────────────────────────────────────────────────────────

def take(tab: str, note: str = "") -> Snapshot:
    """Snapshot the current state of a tab.

    Called by every mutating tool immediately before it writes. Reads
    the whole table into memory and stores it. The read is cheap
    because the adapter has already read it, in most cases — but we
    read fresh here to be certain the snapshot matches what the tool
    actually saw.

    Raises ValueError if the tab does not exist.
    """
    adapter = sheet()
    try:
        data = adapter.read_tab(tab, sample=0)  # sample=0 means "all rows"
    except FileNotFoundError as exc:
        raise ValueError(f"Cannot snapshot {tab!r}: {exc}") from exc

    snap = Snapshot(
        id=_new_id(),
        tab=tab,
        taken_at=time.time(),
        headers=list(data.headers),
        rows=[list(r) for r in data.rows],
        note=str(note or "")[:200],
    )
    _store(snap)
    _prune()
    return snap


def _store(s: Snapshot) -> None:
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO snapshots
                (id, tab, taken_at, headers, rows, row_count, note, undone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                s.id, s.tab, s.taken_at,
                json.dumps(s.headers),
                json.dumps(s.rows, default=str),
                len(s.rows),
                s.note,
                1 if s.undone else 0,
            ),
        )


def _row_to_snapshot(row: sqlite3.Row) -> Snapshot:
    return Snapshot(
        id=row["id"],
        tab=row["tab"],
        taken_at=row["taken_at"],
        headers=json.loads(row["headers"] or "[]"),
        rows=json.loads(row["rows"] or "[]"),
        note=row["note"] or "",
        undone=bool(row["undone"]),
    )


def _prune() -> None:
    """Keep only the newest MAX_SNAPSHOTS snapshots."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT id FROM snapshots ORDER BY taken_at DESC"
        ).fetchall()
        if len(rows) <= MAX_SNAPSHOTS:
            return
        stale = [r["id"] for r in rows[MAX_SNAPSHOTS:]]
        placeholders = ",".join("?" * len(stale))
        conn.execute(
            f"DELETE FROM snapshots WHERE id IN ({placeholders})",
            stale,
        )


def get(snap_id: str) -> Snapshot | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snap_id,)
        ).fetchone()
    return _row_to_snapshot(row) if row else None


def latest(tab: str | None = None) -> Snapshot | None:
    """The most recent snapshot, optionally restricted to one tab.

    "Undo the last thing" means this. Used by `undo_last`.
    """
    with _db() as conn:
        if tab:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE tab = ? "
                "AND undone = 0 ORDER BY taken_at DESC LIMIT 1",
                (tab,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE undone = 0 "
                "ORDER BY taken_at DESC LIMIT 1"
            ).fetchone()
    return _row_to_snapshot(row) if row else None


def list_snapshots(tab: str | None = None, limit: int = 20) -> list[Snapshot]:
    with _db() as conn:
        if tab:
            rows = conn.execute(
                "SELECT * FROM snapshots WHERE tab = ? "
                "ORDER BY taken_at DESC LIMIT ?",
                (tab, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM snapshots "
                "ORDER BY taken_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [_row_to_snapshot(r) for r in rows]


# ── restore ───────────────────────────────────────────────────────────

def restore(snap_id: str) -> dict[str, Any]:
    """Restore a tab from a snapshot.

    This is the undo operation. It:

      1. Snapshots the CURRENT state first (so you can undo the undo).
      2. Writes the snapshot's headers and rows back to the tab.
      3. Marks the original snapshot as undone so `latest()` skips it.

    The pre-restore snapshot is important. Without it, undo is a
    one-way door: an accidental restore would lose the current state.

    Returns a dict describing what happened.
    """
    snap = get(snap_id)
    if snap is None:
        return {"ok": False, "why": f"No snapshot with id {snap_id!r}."}

    adapter = sheet()

    # Snapshot what is about to be overwritten, so undo-the-undo works
    pre_id = ""
    try:
        pre = take(snap.tab, note=f"before restoring {snap.id}")
        pre_id = pre.id
    except ValueError:
        # The tab might not exist anymore — that is OK, restoring will
        # recreate it.
        pass

    # Write the snapshot back
    try:
        values = [list(snap.headers)] + [list(r) for r in snap.rows]
        if not snap.headers:
            # Empty snapshot — clear the tab if it exists
            try:
                adapter.delete_tab(snap.tab)
            except Exception:
                pass
            adapter.create_tab(snap.tab)
        else:
            adapter.write_range(snap.tab, "A1", values)
    except Exception as exc:
        return {
            "ok": False,
            "why": f"Could not restore {snap.id}: {exc}",
            "pre_snapshot": pre_id,
        }

    _mark_undone(snap.id)

    return {
        "ok": True,
        "restored": snap.id,
        "tab": snap.tab,
        "rows": snap.row_count,
        "pre_snapshot": pre_id,
        "say": (
            f"Restored {snap.tab!r} from {snap.id} "
            f"({snap.row_count} rows, taken {snap.when}).\n"
            f"Before restoring, I snapshotted the current state as "
            f"{pre_id} — say 'undo' again to reverse this."
        ),
    }


def _mark_undone(snap_id: str) -> None:
    with _db() as conn:
        conn.execute(
            "UPDATE snapshots SET undone = 1 WHERE id = ?", (snap_id,)
        )


# ── summary ───────────────────────────────────────────────────────────

def describe(snap: Snapshot) -> str:
    """One human line, for the CLI."""
    tag = " (already undone)" if snap.undone else ""
    note = f" — {snap.note}" if snap.note else ""
    return (
        f"{snap.id}  {snap.tab}  {snap.row_count} rows  "
        f"{snap.when}{note}{tag}"
    )


def list_say(tab: str | None = None) -> str:
    snaps = list_snapshots(tab)
    if not snaps:
        return "No snapshots yet."
    return "\n".join(describe(s) for s in snaps)
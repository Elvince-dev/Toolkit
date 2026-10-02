"""SQLite adapter. One table per tab.

Contract, chosen to match CsvFolderAdapter so the brain cannot tell
the difference:

    list_tabs()            →  table names
    read_tab(name, sample) →  TabData where headers are column names
                              and rows are the table rows
    write_range(tab, a1, values)
                           →  A1 anchor is honoured:
                                "A1" → replace all rows (headers = values[0])
                                "A3" → start writing at data row 3
    append_rows(tab, rows) →  add rows at the end, same header order
    create_tab(name)       →  CREATE TABLE with one placeholder column
    delete_tab(name)       →  DROP TABLE
    current_selection()    →  None (SQLite has no UI)

Differences from the CSV adapter, and why:

  * SQLite refuses to have a table with zero columns. A fresh "tab"
    is therefore a table with one column named `_placeholder`. The
    first write_range at A1 DROPs it and rebuilds with the real
    columns. list_tabs and read_tab hide this from the caller, so a
    fresh tab looks empty, exactly like a fresh CSV file.
  * There is no "file" to write atomically — SQLite transactions
    handle that. Every method opens a connection, does its work,
    commits, closes.
  * Column types are enforced by SQLite, not by us. We read
    everything back as str via `_cell`, so the brain always sees
    the same shape it does from CSV.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from toolkit.adapters.base import Selection, TabData


_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_PLACEHOLDER = "_placeholder"


class SqliteAdapter:
    """Each table in the database is one tab."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Touch the file so a fresh start works.
        with self._db():
            pass

    # ── required ──────────────────────────────────────────────────────

    def list_tabs(self) -> list[str]:
        """Every table, including ones that are placeholder-only.

        A placeholder-only table is a "fresh tab" that was created
        but never written to. It appears in the list because the user
        created it. read_tab returns empty headers for it.
        """
        with self._db() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()
        return [r["name"] for r in rows]

    def read_tab(self, name: str, *, sample: int = 300) -> TabData:
        table = self._table(name)
        with self._db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                raise FileNotFoundError(f"No tab called {name!r}")

            cols_info = conn.execute(
                f"PRAGMA table_info({_quote(table)})"
            ).fetchall()
            headers = [c["name"] for c in cols_info]

            # A fresh tab is a table with only the placeholder column.
            # The outside world sees it as having no columns.
            if not headers or headers == [_PLACEHOLDER]:
                return TabData(name=name, headers=[], rows=[])

            count = conn.execute(
                f"SELECT COUNT(*) AS n FROM {_quote(table)}"
            ).fetchone()["n"]

            limit = sample if sample else count
            rows_raw = conn.execute(
                f"SELECT * FROM {_quote(table)} LIMIT ?",
                (limit,),
            ).fetchall()

        rows = [[_cell(v) for v in r] for r in rows_raw]
        return TabData(name=name, headers=headers, rows=rows)

    def write_range(
        self, tab: str, a1: str, values: list[list[Any]]
    ) -> None:
        """Write a rectangle of cells at an A1 anchor.

        A1 semantics:
            A1  → values[0] becomes the header row (the columns), and
                  values[1:] become the data. This REPLACES the table.
            A3  → values become data rows starting at row 2 of the
                  table (sheet row 3). The table must already exist
                  and have headers.
        """
        if not values or not values[0]:
            return

        start_row, _start_col = _parse_a1(a1)
        table = self._table(tab)

        with self._db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name=?",
                (table,),
            ).fetchone()

            if start_row == 0:
                # A1: replace the table entirely. values[0] is headers.
                headers = [_cell(c) for c in values[0]]
                data_rows = [[_cell(c) for c in row] for row in values[1:]]
                self._replace_table(conn, table, headers, data_rows)
                return

            if not exists:
                raise FileNotFoundError(
                    f"No tab called {tab!r}. Write to A1 first to "
                    f"create it."
                )

            cols_info = conn.execute(
                f"PRAGMA table_info({_quote(table)})"
            ).fetchall()
            headers = [c["name"] for c in cols_info]

            # A placeholder-only table has no data columns yet.
            if not headers or headers == [_PLACEHOLDER]:
                raise ValueError(
                    f"Tab {tab!r} has no columns yet. Write to A1 "
                    f"with a header row first."
                )

            # Pad every incoming row to the header width.
            width = len(headers)
            padded: list[list[str]] = []
            for row in values:
                r = [_cell(c) for c in row]
                while len(r) < width:
                    r.append("")
                padded.append(r[:width])

            # start_row is 0-based (sheet row - 1). Data row 0 is the
            # first row AFTER the header row, so A2 means sheet row 2
            # means data row 0.
            data_row = start_row - 1
            if data_row < 0:
                data_row = 0

            quoted_cols = ", ".join(_quote(h) for h in headers)
            placeholders = ", ".join("?" * width)

            # Delete everything from data_row onwards, by rowid order.
            conn.execute(
                f"DELETE FROM {_quote(table)} "
                f"WHERE rowid IN ("
                f"  SELECT rowid FROM {_quote(table)} "
                f"  ORDER BY rowid LIMIT -1 OFFSET ?"
                f")",
                (data_row,),
            )

            # Pad blanks if the write starts beyond the current end.
            current = conn.execute(
                f"SELECT COUNT(*) AS n FROM {_quote(table)}"
            ).fetchone()["n"]
            for _ in range(max(0, data_row - current)):
                conn.execute(
                    f"INSERT INTO {_quote(table)} ({quoted_cols}) "
                    f"VALUES ({placeholders})",
                    ["" for _ in range(width)],
                )

            for row in padded:
                conn.execute(
                    f"INSERT INTO {_quote(table)} ({quoted_cols}) "
                    f"VALUES ({placeholders})",
                    row,
                )

    def append_rows(self, tab: str, rows: list[list[Any]]) -> None:
        if not rows:
            return
        table = self._table(tab)

        with self._db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                raise FileNotFoundError(f"No tab called {tab!r}")

            cols_info = conn.execute(
                f"PRAGMA table_info({_quote(table)})"
            ).fetchall()
            headers = [c["name"] for c in cols_info]

            # A placeholder-only table has no data columns yet.
            if not headers or headers == [_PLACEHOLDER]:
                raise ValueError(
                    f"Tab {tab!r} has no columns — cannot append. "
                    f"Write to A1 with a header row first."
                )

            width = len(headers)
            placeholders = ", ".join("?" * width)
            quoted_cols = ", ".join(_quote(h) for h in headers)

            for row in rows:
                r = [_cell(c) for c in row]
                while len(r) < width:
                    r.append("")
                conn.execute(
                    f"INSERT INTO {_quote(table)} ({quoted_cols}) "
                    f"VALUES ({placeholders})",
                    r[:width],
                )

    def create_tab(self, name: str) -> None:
        """Create a table with one placeholder column.

        SQLite refuses to have a table with zero columns, so a fresh
        "tab" is a table with one column named `_placeholder`. The
        first write_range at A1 will DROP the placeholder and rebuild
        the table with the real columns. From the outside a fresh tab
        looks empty, exactly like a fresh CSV file.
        """
        table = self._table(name)
        with self._db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if exists:
                raise FileExistsError(
                    f"A tab called {name!r} already exists"
                )
            conn.execute(
                f"CREATE TABLE {_quote(table)} ({_PLACEHOLDER} TEXT)"
            )

    def delete_tab(self, name: str) -> None:
        table = self._table(name)
        with self._db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if exists:
                conn.execute(f"DROP TABLE {_quote(table)}")

    def get_user(self) -> dict[str, str]:
        import os
        return {
            "name": os.environ.get("USER") or os.environ.get("USERNAME") or "you",
            "email": "",
            "timezone": "Africa/Nairobi",
        }

    # ── optional ──────────────────────────────────────────────────────

    def current_selection(self) -> Selection | None:
        return None

    # ── internals ─────────────────────────────────────────────────────

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _table(self, name: str) -> str:
        if not _SAFE_NAME.match(name):
            raise ValueError(
                f"Invalid tab name: {name!r}. "
                f"SQLite table names must start with a letter or "
                f"underscore and contain only letters, digits, and "
                f"underscores."
            )
        return name

    def _replace_table(
        self,
        conn: sqlite3.Connection,
        table: str,
        headers: list[str],
        rows: list[list[str]],
    ) -> None:
        """Drop and rebuild the table with the given columns.

        Runs inside the caller's transaction. If anything fails, the
        original table survives because the whole transaction rolls
        back.
        """
        if not headers:
            return

        # Sanitise headers into column names SQLite accepts.
        clean: list[str] = []
        seen: set[str] = set()
        for i, h in enumerate(headers):
            name = _safe_column(h, i)
            base = name
            n = 1
            while name in seen:
                n += 1
                name = f"{base}_{n}"
            seen.add(name)
            clean.append(name)

        conn.execute(f"DROP TABLE IF EXISTS {_quote(table)}")
        cols_sql = ", ".join(f"{_quote(c)} TEXT" for c in clean)
        conn.execute(f"CREATE TABLE {_quote(table)} ({cols_sql})")

        if not rows:
            return

        width = len(clean)
        placeholders = ", ".join("?" * width)
        quoted = ", ".join(_quote(c) for c in clean)
        for row in rows:
            r = list(row)
            while len(r) < width:
                r.append("")
            conn.execute(
                f"INSERT INTO {_quote(table)} ({quoted}) "
                f"VALUES ({placeholders})",
                r[:width],
            )


# ── module helpers ────────────────────────────────────────────────────

_NON_ALNUM = re.compile(r"[^A-Za-z0-9_]")


def _safe_column(header: str, index: int) -> str:
    """Turn a header into a legal SQLite column name.

    SQLite is permissive — most names work with quoting — but we
    still want clean names so PRAGMA table_info returns what a human
    expects to see.
    """
    s = str(header or "").strip()
    s = _NON_ALNUM.sub("_", s)
    s = s.strip("_")
    if not s or s[0].isdigit():
        s = f"col_{index}"
    return s[:63]


def _quote(name: str) -> str:
    """Quote an identifier for SQLite."""
    return '"' + name.replace('"', '""') + '"'


def _cell(value: Any) -> str:
    """Normalise one cell to a string.

    None becomes "". Everything else goes through str(). Same
    boundary contract as CsvFolderAdapter — the brain never sees a
    None cell, and never sees a non-string cell.
    """
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _parse_a1(a1: str) -> tuple[int, int]:
    """'B3' -> (row=2, col=1). Zero-indexed."""
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", a1.strip())
    if not m:
        raise ValueError(f"Not an A1 reference: {a1!r}")
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    return int(m.group(2)) - 1, col - 1
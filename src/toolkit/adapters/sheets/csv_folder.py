"""A folder of CSV files, one per tab.

The reference adapter. Write it first, test it thoroughly, use it as
the template for the others.

Design notes:

  * Reads with polars for speed. Falls back to the stdlib csv module
    if polars is not installed.
  * Writes are atomic: write to a temp file in the same directory,
    then os.replace. A crash mid-write cannot corrupt the CSV.
  * Every cell is read as a STRING. The brain does its own type
    guessing (read_number, read_date) because that is where the
    eighteen months of bug-fixing lives. The adapter must not
    pre-chew the data.
  * Empty cells become "" — never None. Polars represents a blank
    cell as null and would hand back None after cast(Utf8); the brain
    expects "" for an empty cell (matching Google Sheets), so we
    normalise at the boundary. Any future adapter (Postgres, Excel)
    must do the same.
  * Tab names are sanitised. A name like "../../etc/passwd" is
    rejected, not clamped.
  * An empty CSV returns empty headers and no rows.
  * write_range(tab, "A1", values) treats values[0] as the header
    row and values[1:] as data. It REPLACES the whole file — CSV
    has no notion of a partial overwrite. The a1 argument is
    accepted for API symmetry but ignored.
"""

from __future__ import annotations

import csv
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from toolkit.adapters.base import Selection, TabData

try:
    import polars as pl
    _HAS_POLARS = True
except ImportError:
    _HAS_POLARS = False


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-.]{0,99}$")


class CsvFolderAdapter:
    """Each .csv in a folder is one tab."""

    def __init__(self, path: Path | str) -> None:
        self.root = Path(path).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ── required ──────────────────────────────────────────────────────

    def list_tabs(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.csv") if p.is_file())

    def read_tab(self, name: str, *, sample: int = 300) -> TabData:
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"No tab called {name!r}")
        headers, rows = self._read(path, sample=sample)
        return TabData(name=name, headers=headers, rows=rows)

    def write_range(
        self, tab: str, a1: str, values: list[list[Any]]
    ) -> None:
        """Write a rectangle of cells.

        Contract used by every tool:

            write_range(tab, "A1", [headers, *data_rows])

        writes headers as the header row and the remaining rows as
        data. REPLACES the whole file. The a1 argument is accepted
        for API symmetry with cell-based backends but is ignored —
        a CSV file has no partial writes.

        Cell values are cast to strings at this boundary so the file
        is always rectangular and always readable by any consumer.
        """
        if not values or not values[0]:
            return

        path = self._path(tab)
        headers = [_cell(c) for c in values[0]]
        data_rows = [[_cell(c) for c in row] for row in values[1:]]

        # Pad every data row to the header width so the file is
        # rectangular. Without this, reading back gives a different
        # shape than was written.
        width = len(headers)
        for row in data_rows:
            while len(row) < width:
                row.append("")

        self._write(path, headers, data_rows)

    def append_rows(self, tab: str, rows: list[list[Any]]) -> None:
        if not rows:
            return
        path = self._path(tab)
        if not path.exists():
            raise FileNotFoundError(f"No tab called {tab!r}")

        headers, existing = self._read(path, sample=None)
        if not headers:
            raise ValueError(
                f"Tab {tab!r} has no header row — cannot append to it. "
                f"Write the headers first with write_range()."
            )

        width = len(headers)
        padded: list[list[Any]] = []
        for row in rows:
            r = [_cell(c) for c in row]
            while len(r) < width:
                r.append("")
            padded.append(r[:width])

        self._write(path, headers, existing + padded)

    def create_tab(self, name: str) -> None:
        path = self._path(name)
        if path.exists():
            raise FileExistsError(f"A tab called {name!r} already exists")
        path.write_text("", encoding="utf-8")

    def delete_tab(self, name: str) -> None:
        path = self._path(name)
        if path.exists():
            path.unlink()

    def get_user(self) -> dict[str, str]:
        return {
            "name": os.environ.get("USER") or os.environ.get("USERNAME") or "you",
            "email": "",
            "timezone": "Africa/Nairobi",
        }

    # ── optional ──────────────────────────────────────────────────────

    def current_selection(self) -> Selection | None:
        """CSV folders have no UI, so there is never a selection."""
        return None

    # ── internals ─────────────────────────────────────────────────────

    def _path(self, name: str) -> Path:
        """Turn a tab name into a file path, safely.

        Rejects names that are not a plain identifier. This is why
        someone cannot ask the agent to "read ../../etc/passwd" and
        have it work.
        """
        if not _SAFE_NAME.match(name):
            raise ValueError(
                f"Invalid tab name: {name!r}. "
                f"Use letters, digits, spaces, and basic punctuation."
            )
        return self.root / f"{name}.csv"

    def _read(
        self, path: Path, *, sample: int | None
    ) -> tuple[list[str], list[list[Any]]]:
        """Read a CSV. Returns (headers, rows).

        An empty file returns ([], []). This is the state immediately
        after create_tab().

        Every cell is returned as a string. Empty cells are "". The
        brain does its own type inference on top of that.
        """
        if path.stat().st_size == 0:
            return [], []
        if _HAS_POLARS:
            return self._read_polars(path, sample)
        return self._read_csv(path, sample)

    def _read_polars(
        self, path: Path, sample: int | None
    ) -> tuple[list[str], list[list[Any]]]:
        kwargs: dict[str, Any] = {
            "infer_schema_length": 0,   # everything is a string
            "truncate_ragged_lines": True,
            "ignore_errors": True,
        }
        if sample:
            kwargs["n_rows"] = sample
        df = pl.read_csv(path, **kwargs)
        headers = list(df.columns)
        # Cast every column to text and turn nulls into empty strings.
        # Without fill_null, a blank cell comes back as None and the
        # brain's parsing.py treats None and "" differently on purpose
        # — None means "never read", "" means "empty cell".
        df = df.cast(pl.Utf8).fill_null("")
        rows = [list(r) for r in df.rows()]
        return headers, rows

    def _read_csv(
        self, path: Path, sample: int | None
    ) -> tuple[list[str], list[list[Any]]]:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            try:
                headers = next(reader)
            except StopIteration:
                return [], []
            headers = [str(h) for h in headers]
            rows: list[list[Any]] = []
            for i, row in enumerate(reader):
                if sample is not None and i >= sample:
                    break
                # Pad short rows to header width; truncate long ones.
                while len(row) < len(headers):
                    row.append("")
                rows.append(list(row[: len(headers)]))
            return headers, rows

    def _write(
        self, path: Path, headers: list[str], rows: list[list[Any]]
    ) -> None:
        """Atomically replace the CSV.

        Writes to a temp file in the same directory (so os.replace
        is atomic on POSIX and near-atomic on Windows), then swaps.
        A crash mid-write leaves the original intact.
        """
        fd, tmp_name = tempfile.mkstemp(
            suffix=".csv.tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(headers)
                for row in rows:
                    writer.writerow(row)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


# ── module-level helpers ───────────────────────────────────────────────

def _cell(value: Any) -> str:
    """Normalise one cell value to a string.

    None becomes "". Everything else goes through str(). This is the
    adapter's boundary function — the brain never sees a None cell,
    and it never sees a non-string cell either.
    """
    if value is None:
        return ""
    return str(value)


def _parse_a1(a1: str) -> tuple[int, int]:
    """'B3' -> (row=2, col=1). Zero-indexed.

    Kept for future adapters that DO support partial writes (Excel,
    Google Sheets). The CSV adapter ignores it.
    """
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", a1.strip())
    if not m:
        raise ValueError(f"Not an A1 reference: {a1!r}")
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    return int(m.group(2)) - 1, col - 1
"""The SQLite adapter, tested against the same contract as the CSV
adapter.

Every test in here corresponds to a test in test_csv_adapter.py.
The assertions are IDENTICAL. If both pass, the adapter interface is
genuinely portable — the brain cannot tell the difference between a
folder of CSVs and a SQLite database.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.adapters.sheets.sqlite import SqliteAdapter


@pytest.fixture
def adapter(tmp_path: Path) -> SqliteAdapter:
    return SqliteAdapter(tmp_path / "toolkit.db")


# ── files and tabs ────────────────────────────────────────────────────

def test_create_and_list(adapter):
    adapter.create_tab("Sales")
    adapter.create_tab("Contacts")
    assert adapter.list_tabs() == ["Contacts", "Sales"]


def test_create_twice_raises(adapter):
    adapter.create_tab("Sales")
    with pytest.raises(FileExistsError):
        adapter.create_tab("Sales")


def test_delete(adapter):
    adapter.create_tab("Sales")
    adapter.delete_tab("Sales")
    assert adapter.list_tabs() == []


def test_delete_missing_is_silent(adapter):
    """Deleting a tab that does not exist does not raise."""
    adapter.delete_tab("Nope")  # no exception
    assert adapter.list_tabs() == []


# ── write_range ───────────────────────────────────────────────────────

def test_write_and_read_roundtrip(adapter):
    adapter.create_tab("Sales")
    adapter.write_range("Sales", "A1", [
        ["Region", "Amount", "Date"],
        ["Thika", "4200", "2026-01-15"],
        ["Ruaka", "3100", "2026-01-16"],
    ])
    tab = adapter.read_tab("Sales")
    assert tab.headers == ["Region", "Amount", "Date"]
    assert tab.row_count == 2
    assert tab.rows[0] == ["Thika", "4200", "2026-01-15"]


def test_cells_are_strings(adapter):
    """The adapter must not pre-type values — the brain does that."""
    adapter.create_tab("Sales")
    adapter.write_range("Sales", "A1", [
        ["A", "B"],
        [1, 2.5],
    ])
    tab = adapter.read_tab("Sales")
    assert tab.rows[0] == ["1", "2.5"]


def test_write_range_replaces_the_file(adapter):
    """write_range at A1 replaces the whole table, same as CSV."""
    adapter.create_tab("Sales")
    adapter.write_range("Sales", "A1", [["H1", "H2"], ["a", "b"]])
    adapter.write_range("Sales", "A1", [["H1", "H2"], ["c", "d"]])
    tab = adapter.read_tab("Sales")
    assert tab.rows == [["c", "d"]]


def test_write_range_writes_into_a_missing_tab(adapter):
    """Calling write_range on a tab that does not exist yet creates it.

    This is a SQLite-specific behaviour: unlike CSV, there is no file
    to create; the table is created on the first write.
    """
    adapter.write_range("Fresh", "A1", [["H"], ["a"]])
    tab = adapter.read_tab("Fresh")
    assert tab.headers == ["H"]
    assert tab.rows == [["a"]]


def test_write_range_pads_short_rows(adapter):
    """Ragged rows are padded to header width."""
    adapter.create_tab("Ragged")
    adapter.write_range("Ragged", "A1", [
        ["A", "B", "C"],
        ["1"],
        ["1", "2"],
        ["1", "2", "3"],
    ])
    tab = adapter.read_tab("Ragged")
    assert tab.rows == [
        ["1", "", ""],
        ["1", "2", ""],
        ["1", "2", "3"],
    ]


# ── append_rows ───────────────────────────────────────────────────────

def test_append_rows(adapter):
    adapter.create_tab("Sales")
    adapter.write_range("Sales", "A1", [["H1", "H2"], ["a", "b"]])
    adapter.append_rows("Sales", [["c", "d"], ["e", "f"]])
    tab = adapter.read_tab("Sales")
    assert tab.row_count == 3
    assert tab.rows[1] == ["c", "d"]
    assert tab.rows[2] == ["e", "f"]


def test_append_rows_pads_to_header_width(adapter):
    adapter.create_tab("Sales")
    adapter.write_range("Sales", "A1", [["A", "B", "C"], ["1", "2", "3"]])
    adapter.append_rows("Sales", [["only-one"]])
    tab = adapter.read_tab("Sales")
    assert tab.rows[-1] == ["only-one", "", ""]


def test_append_rows_to_missing_tab_raises(adapter):
    with pytest.raises(FileNotFoundError):
        adapter.append_rows("Nope", [["a"]])


def test_append_rows_to_empty_tab_raises(adapter):
    """A freshly created table has no columns, so append cannot proceed."""
    adapter.create_tab("Empty")
    with pytest.raises(ValueError):
        adapter.append_rows("Empty", [["a"]])


# ── read_tab ──────────────────────────────────────────────────────────

def test_sample_limits_rows(adapter):
    adapter.create_tab("Big")
    rows = [["H"]] + [[f"row{i}"] for i in range(100)]
    adapter.write_range("Big", "A1", rows)
    tab = adapter.read_tab("Big", sample=10)
    assert tab.row_count == 10


def test_read_missing_raises(adapter):
    with pytest.raises(FileNotFoundError):
        adapter.read_tab("Nope")


def test_read_empty_tab_returns_nothing(adapter):
    adapter.create_tab("Empty")
    tab = adapter.read_tab("Empty")
    assert tab.headers == []
    assert tab.rows == []
    assert tab.row_count == 0


# ── safety ────────────────────────────────────────────────────────────

def test_bad_tab_name_rejected(adapter):
    for bad in ("../../etc/passwd", "bad/name", "", "../escape", "has space"):
        with pytest.raises(ValueError):
            adapter._table(bad)


def test_bad_path_is_rejected_without_touching_files(adapter):
    """A rejected tab name must not create, read, or modify any table."""
    adapter.create_tab("Sales")
    adapter.write_range("Sales", "A1", [["H"], ["a"]])
    with pytest.raises(ValueError):
        adapter.write_range("../escape", "A1", [["x"]])
    # The real table is untouched
    assert adapter.read_tab("Sales").row_count == 1


# ── optional methods ──────────────────────────────────────────────────

def test_selection_is_none(adapter):
    """SQLite has no UI, so there is never a selection."""
    assert adapter.current_selection() is None


def test_get_user_returns_a_dict(adapter):
    user = adapter.get_user()
    assert isinstance(user, dict)
    assert "name" in user
    assert "timezone" in user


# ── SQLite-specific: A1 anchor behaviour ──────────────────────────────

def test_write_below_existing_row(adapter):
    """Writing to A3 starts at data row 2."""
    adapter.create_tab("Sales")
    adapter.write_range("Sales", "A1", [
        ["H1", "H2"],
        ["a", "b"],
        ["c", "d"],
        ["e", "f"],
    ])
    # Replace from A3 onward — keeps row 1, replaces rows 2 and 3
    adapter.write_range("Sales", "A3", [["X", "Y"]])
    tab = adapter.read_tab("Sales")
    assert tab.rows[0] == ["a", "b"]
    assert tab.rows[1] == ["X", "Y"]
    assert tab.row_count == 2
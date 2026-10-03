"""The writing tools, tested against real files."""

from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.adapters import registry as adapter_registry
from toolkit.brain import snapshot as snap_mod
from toolkit.config import settings
from toolkit.tools import registry as tool_registry


@pytest.fixture(autouse=True)
def fresh_state(tmp_path: Path, monkeypatch):
    """A fresh CSV folder and snapshots DB for every test."""
    monkeypatch.setenv("TOOLKIT_SHEET_ADAPTER", "csv")
    monkeypatch.setenv("TOOLKIT_CSV_PATH", str(tmp_path / "csv"))
    monkeypatch.setenv("TOOLKIT_DATA_DIR", str(tmp_path))
    settings.cache_clear()
    adapter_registry.reset()
    tool_registry.reset()
    yield
    settings.cache_clear()
    adapter_registry.reset()
    tool_registry.reset()


@pytest.fixture
def sales(tmp_path: Path) -> None:
    from toolkit.adapters.sheets.csv_folder import CsvFolderAdapter

    adapter = CsvFolderAdapter(tmp_path / "csv")
    adapter.create_tab("Sales")
    adapter.write_range("Sales", "A1", [
        ["Region", "Amount", "Rep"],
        ["Thika", "4200", "Ann"],
        ["Ruaka", "3100", "Bob"],
        ["Thika", "5100", "Ann"],
    ])


# ── write_cell ────────────────────────────────────────────────────────

def test_write_cell_changes_one_value(sales):
    tools = tool_registry.load_tools()
    out = tools["write_cell"].run({
        "tab": "Sales", "a1": "B2", "value": "9999",
    })
    assert "Wrote" in out or "wrote" in out

    from toolkit.adapters.registry import sheet
    tab = sheet().read_tab("Sales")
    assert tab.rows[0][1] == "9999"


def test_write_cell_takes_a_snapshot(sales):
    tools = tool_registry.load_tools()
    tools["write_cell"].run({"tab": "Sales", "a1": "B2", "value": "x"})
    snaps = snap_mod.list_snapshots("Sales")
    assert len(snaps) == 1
    assert snaps[0].row_count == 3


def test_write_cell_rejects_a_range(sales):
    tools = tool_registry.load_tools()
    out = tools["write_cell"].run({
        "tab": "Sales", "a1": "A1:B2", "value": "x",
    })
    assert "not a cell" in out.lower() or "cell reference" in out.lower()


def test_write_cell_missing_tab(sales):
    tools = tool_registry.load_tools()
    out = tools["write_cell"].run({
        "tab": "Nope", "a1": "A1", "value": "x",
    })
    assert "no tab" in out.lower()


# ── append_row ────────────────────────────────────────────────────────

def test_append_row_adds_a_row(sales):
    tools = tool_registry.load_tools()
    out = tools["append_row"].run({
        "tab": "Sales", "values": ["Nairobi", "2800", "Carol"],
    })
    assert "Appended" in out

    from toolkit.adapters.registry import sheet
    tab = sheet().read_tab("Sales")
    assert tab.row_count == 4
    assert tab.rows[-1] == ["Nairobi", "2800", "Carol"]


def test_append_row_accepts_comma_string(sales):
    tools = tool_registry.load_tools()
    out = tools["append_row"].run({
        "tab": "Sales", "values": "Nairobi,2800,Carol",
    })
    assert "Appended" in out


# ── fill_column ───────────────────────────────────────────────────────

def test_fill_column_with_literal(sales):
    tools = tool_registry.load_tools()
    out = tools["fill_column"].run({
        "tab": "Sales", "column": "C", "value": "TBD",
        "first": 2, "last": 4,
    })
    assert "Filled" in out

    from toolkit.adapters.registry import sheet
    tab = sheet().read_tab("Sales")
    assert all(row[2] == "TBD" for row in tab.rows)


def test_fill_column_upper(sales):
    tools = tool_registry.load_tools()
    tools["fill_column"].run({
        "tab": "Sales", "column": "A", "value": "@upper",
    })
    from toolkit.adapters.registry import sheet
    tab = sheet().read_tab("Sales")
    assert tab.rows[0][0] == "THIKA"


# ── clean_column ──────────────────────────────────────────────────────

def test_clean_column_trims(sales):
    from toolkit.adapters.registry import sheet
    adapter = sheet()
    adapter.write_range("Sales", "A1", [
        ["Region", "Amount", "Rep"],
        ["  Thika  ", "4200", "Ann"],
        [" Ruaka", "3100", "Bob"],
        ["Thika", "5100", "Ann"],
    ])

    tools = tool_registry.load_tools()
    out = tools["clean_column"].run({"tab": "Sales", "column": "Region"})
    assert "trimmed" in out.lower() or "Cleaned" in out

    tab = adapter.read_tab("Sales")
    assert tab.rows[0][0] == "Thika"
    assert tab.rows[1][0] == "Ruaka"


def test_clean_column_merges_casing(sales):
    from toolkit.adapters.registry import sheet
    adapter = sheet()
    adapter.write_range("Sales", "A1", [
        ["Region", "Amount"],
        ["Thika", "4200"],
        ["thika", "3100"],
        ["THIKA", "5100"],
        ["Ruaka", "2800"],
    ])

    tools = tool_registry.load_tools()
    out = tools["clean_column"].run({"tab": "Sales", "column": "Region"})
    assert "merged" in out.lower() or "Cleaned" in out

    tab = adapter.read_tab("Sales")
    # All three "thika*" should collapse to "Thika"
    assert sum(1 for r in tab.rows if r[0] == "Thika") == 3


def test_clean_column_reports_when_already_clean(sales):
    tools = tool_registry.load_tools()
    out = tools["clean_column"].run({"tab": "Sales", "column": "Rep"})
    assert "already clean" in out.lower()


# ── undo_last ─────────────────────────────────────────────────────────

def test_undo_restores_a_write(sales):
    tools = tool_registry.load_tools()

    from toolkit.adapters.registry import sheet
    before = sheet().read_tab("Sales").rows

    tools["write_cell"].run({"tab": "Sales", "a1": "B2", "value": "9999"})
    after = sheet().read_tab("Sales").rows
    assert after != before

    out = tools["undo_last"].run({"tab": "Sales"})
    assert "Restored" in out or "restored" in out

    restored = sheet().read_tab("Sales").rows
    assert restored == before


def test_undo_with_nothing_to_undo(sales):
    tools = tool_registry.load_tools()
    out = tools["undo_last"].run({"tab": "Sales"})
    assert "no snapshot" in out.lower() or "nothing" in out.lower()


# ── delete_tab ────────────────────────────────────────────────────────

def test_delete_tab_needs_confirmation(sales):
    tools = tool_registry.load_tools()
    out = tools["delete_tab"].run({"tab": "Sales"})

    from toolkit.adapters.registry import sheet
    assert "Sales" in sheet().list_tabs()  # still there
    assert "not reversible" in out.lower() or "say" in out.lower()


def test_delete_tab_proceeds_with_confirm(sales):
    tools = tool_registry.load_tools()
    out = tools["delete_tab"].run({"tab": "Sales", "confirm": True})

    from toolkit.adapters.registry import sheet
    assert "Sales" not in sheet().list_tabs()
    assert "Deleted" in out


def test_delete_tab_undo_works(sales):
    tools = tool_registry.load_tools()
    tools["delete_tab"].run({"tab": "Sales", "confirm": True})

    from toolkit.adapters.registry import sheet
    assert "Sales" not in sheet().list_tabs()

    tools["undo_last"].run({"tab": "Sales"})
    assert "Sales" in sheet().list_tabs()


# ── list_snapshots ────────────────────────────────────────────────────

def test_list_snapshots_empty(sales):
    tools = tool_registry.load_tools()
    out = tools["list_snapshots"].run({})
    assert "no snapshots" in out.lower()


def test_list_snapshots_after_write(sales):
    tools = tool_registry.load_tools()
    tools["write_cell"].run({"tab": "Sales", "a1": "B2", "value": "x"})
    out = tools["list_snapshots"].run({"tab": "Sales"})
    assert "Sales" in out
    assert "s-" in out  # snapshot id prefix
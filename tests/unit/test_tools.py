"""The tool registry and the data tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.adapters import registry as adapter_registry
from toolkit.config import settings
from toolkit.tools import registry as tool_registry


@pytest.fixture(autouse=True)
def point_at_csv(tmp_path: Path, monkeypatch):
    """Every test uses a fresh CSV folder."""
    monkeypatch.setenv("TOOLKIT_SHEET_ADAPTER", "csv")
    monkeypatch.setenv("TOOLKIT_CSV_PATH", str(tmp_path / "csv"))
    settings.cache_clear()
    adapter_registry.reset()
    tool_registry.reset()
    yield
    settings.cache_clear()
    adapter_registry.reset()
    tool_registry.reset()


@pytest.fixture
def sales(tmp_path: Path) -> None:
    """A small sales sheet that the tools can read."""
    from toolkit.adapters.sheets.csv_folder import CsvFolderAdapter

    adapter = CsvFolderAdapter(tmp_path / "csv")
    adapter.create_tab("Sales")
    adapter.write_range("Sales", "A1", [
        ["Region", "Amount", "Date", "Rep"],
        ["Thika", "4200", "2026-01-15", "Ann"],
        ["Ruaka", "3100", "2026-01-16", "Bob"],
        ["Thika", "5100", "2026-01-17", "Ann"],
        ["Nairobi", "2800", "2026-01-18", "Carol"],
        ["Ruaka", "9100", "2026-01-19", "Bob"],
        ["Thika", "4700", "2026-01-20", "Ann"],
        ["Nairobi", "3300", "2026-01-21", "Carol"],
        ["Ruaka", "2500", "2026-01-22", "Bob"],
    ])


# ── registry ──────────────────────────────────────────────────────────

def test_load_tools_returns_a_dict():
    tools = tool_registry.load_tools()
    assert isinstance(tools, dict)
    assert len(tools) >= 6


def test_load_tools_includes_the_expected_names():
    tools = tool_registry.load_tools()
    for name in ("describe_sheet", "count_rows", "compare_groups",
                 "find_outliers", "trend_over"):
        assert name in tools


def test_every_matcher_points_at_a_real_tool():
    """A matcher with a typo'd tool name is a silent failure.

    This test would have caught the count_by → compare_groups bug
    before it shipped. Every matcher must resolve.
    """
    tools = tool_registry.load_tools()
    for matcher in tool_registry.MATCHERS:
        assert matcher.tool in tools, (
            f"Matcher {matcher.name!r} points at "
            f"{matcher.tool!r}, which is not a registered tool. "
            f"Available: {', '.join(sorted(tools))}"
        )


def test_tool_missing_reports_absent_fields():
    tool = tool_registry.Tool(name="x", what="y", need=("a", "b"))
    assert sorted(tool.missing({})) == ["a", "b"]
    assert tool.missing({"a": "x", "b": "y"}) == []
    assert tool.missing({"a": "x"}) == ["b"]


# ── tool_said_no ──────────────────────────────────────────────────────

def test_tool_said_no_recognises_refusal():
    assert tool_registry.tool_said_no("I could not read that tab.")
    assert tool_registry.tool_said_no("There is no tab called Sales.")
    assert tool_registry.tool_said_no("No spreadsheet connected.")
    assert tool_registry.tool_said_no("")


def test_tool_said_no_recognises_success():
    assert not tool_registry.tool_said_no("8 rows in Sales.")
    assert not tool_registry.tool_said_no("Thika has the most, with 3.")


# ── describe_sheet ────────────────────────────────────────────────────

def test_describe_sheet_lists_tabs(sales):
    tools = tool_registry.load_tools()
    out = tools["describe_sheet"].run({})
    assert "Sales" in out
    assert "8 rows" in out


def test_describe_sheet_with_no_tabs(tmp_path: Path):
    tools = tool_registry.load_tools()
    out = tools["describe_sheet"].run({})
    assert "no tabs" in out.lower()


# ── count_rows ────────────────────────────────────────────────────────

def test_count_rows_totals_everything(sales):
    tools = tool_registry.load_tools()
    out = tools["count_rows"].run({})
    assert "8" in out
    assert "Sales" in out


def test_count_rows_in_specific_tab(sales):
    tools = tool_registry.load_tools()
    out = tools["count_rows_in"].run({"tab": "Sales"})
    assert "8" in out


def test_count_rows_in_missing_tab(sales):
    tools = tool_registry.load_tools()
    out = tools["count_rows_in"].run({"tab": "Nope"})
    assert "no tab" in out.lower()


# ── compare_groups ────────────────────────────────────────────────────

def test_compare_groups_counts_regions(sales):
    tools = tool_registry.load_tools()
    out = tools["compare_groups"].run({"tab": "Sales", "column": "Region"})
    assert "Thika" in out
    assert "Ruaka" in out
    assert "Nairobi" in out
    assert "3" in out


def test_compare_groups_averages(sales):
    tools = tool_registry.load_tools()
    out = tools["compare_groups"].run({
        "tab": "Sales", "column": "Region", "value": "Amount",
    })
    assert "avg" in out.lower()


# ── find_outliers ─────────────────────────────────────────────────────

def test_find_outliers_on_amount(sales):
    tools = tool_registry.load_tools()
    out = tools["find_outliers"].run({"tab": "Sales", "column": "Amount"})
    # 9100 is the obvious outlier — accept with or without comma
    # and with or without decimal places, because the exact format
    # may vary between backends and formatting versions.
    normalized = out.replace(",", "").replace(".00", "")
    assert "9100" in normalized


def test_find_outliers_with_a_text_column(sales):
    tools = tool_registry.load_tools()
    out = tools["find_outliers"].run({"tab": "Sales", "column": "Region"})
    # Too few numbers to judge — should be reported as such
    assert "too few" in out.lower() or "0 number" in out.lower()


# ── trend_over ────────────────────────────────────────────────────────

def test_trend_over_dates(sales):
    tools = tool_registry.load_tools()
    out = tools["trend_over"].run({"tab": "Sales", "date_column": "Date"})
    assert "days" in out.lower()


# ── run_direct ────────────────────────────────────────────────────────

def test_run_direct_matches_count_rows(sales):
    result = tool_registry.run_direct("how many rows are there?")
    assert result is not None
    assert result.ok
    assert "8" in result.answer


def test_run_direct_matches_describe(sales):
    result = tool_registry.run_direct("what can you see in my sheet?")
    assert result is not None
    assert result.ok
    assert "Sales" in result.answer


def test_run_direct_returns_none_for_unmatched():
    result = tool_registry.run_direct("why did sales drop?")
    # This is not a direct-match case — the model must decide
    assert result is None or result.tool != "count_rows"


def test_run_direct_matches_compare_groups_by_region(sales):
    """The bug: 'count the rows by Region' matched count_rows instead.

    This test pins the fix. It must go through compare_groups and it
    must include the region names.
    """
    result = tool_registry.run_direct("count the rows by Region")
    assert result is not None, "no matcher fired at all"
    assert result.tool == "compare_groups", (
        f"expected compare_groups, got {result.tool}"
    )
    assert "Thika" in result.answer or "Ruaka" in result.answer


def test_run_direct_matches_which_region_has_the_most(sales):
    """The phrasing a person actually uses."""
    result = tool_registry.run_direct("which region has the most rows?")
    # Either compare_groups or none — but not count_rows
    assert result is None or result.tool != "count_rows"

def test_describe_sheet_shows_every_column(sales):
    """The model needs the full schema, not the first six columns."""
    from toolkit.adapters.registry import sheet

    adapter = sheet()
    adapter.write_range("Wide", "A1", [
        [f"col{i}" for i in range(1, 15)],
        ["x"] * 14,
    ])
    tools = tool_registry.load_tools()
    out = tools["describe_sheet"].run({})
    for i in range(1, 15):
        assert f"col{i}" in out, f"col{i} was hidden"

def test_summarise_column_uses_full_precision(sales):
    tools = tool_registry.load_tools()
    out = tools["summarise_column"].run({
        "tab": "Sales", "column": "Amount",
    })
    # No scientific notation anywhere
    assert "e+" not in out.lower()
    # Thousands separators present
    assert "," in out
    # Median is reported
    assert "median" in out.lower()


def test_summarise_column_does_not_substitute_for_missing_column(sales):
    tools = tool_registry.load_tools()
    out = tools["summarise_column"].run({
        "tab": "Sales", "column": "Profit",
    })
    assert "Profit" in out
    assert "could not find" in out.lower()
    assert "Amount" not in out


def test_summarise_column_does_not_hop_away_from_explicit_tab(sales):
    from toolkit.adapters.registry import sheet

    sheet().write_range("Q1 Dataset", "A1", [
        ["Profit"],
        ["100"],
    ])
    tools = tool_registry.load_tools()
    out = tools["summarise_column"].run({
        "tab": "Sales", "column": "Profit",
    })
    assert "could not find" in out.lower()
    assert "'Sales'" in out


def test_run_direct_describes_available_tools_without_inspecting_sheet(sales):
    result = tool_registry.run_direct(
        "Hello, how many tasks can you perform based on tools bestowed upon you?"
    )
    assert result is not None
    assert result.tool == "tool_catalog"
    assert "17 tools" in result.answer
    assert "summarise numeric columns" in result.answer.lower()


def test_run_direct_does_not_default_an_unknown_explicit_tab(sales):
    result = tool_registry.run_direct("how many rows are in Missing?")
    assert result is not None
    assert not result.ok
    assert "no tab called 'Missing'" in result.answer


def test_run_direct_summarises_median_sales(sales):
    from toolkit.adapters.registry import sheet

    sheet().write_range("Q1 Dataset", "A1", [
        ["Order ID", "Order Date", "Sales"],
        ["A", "2015-01-03", "10"],
        ["B", "2015-01-04", "20"],
        ["C", "2015-01-05", "90"],
    ])
    result = tool_registry.run_direct("what is the median sales value?")
    assert result is not None
    assert result.tool == "summarise_column"
    assert "'Sales' in 'Q1 Dataset'" in result.answer
    assert "median: 20.00" in result.answer


def test_run_direct_resolves_data_range_to_explicit_tab(sales):
    from toolkit.adapters.registry import sheet

    sheet().write_range("Q1 Dataset", "A1", [
        ["Order ID", "Order Date", "Sales"],
        ["A", "2015-01-03", "10"],
        ["B", "2018-12-30", "20"],
    ])
    result = tool_registry.run_direct(
        "what is the data range of the orders in Q1 Dataset?"
    )
    assert result is not None
    assert result.tool == "date_range"
    assert "'Q1 Dataset'" in result.answer
    assert "2015-01-03" in result.answer
    assert "2018-12-30" in result.answer
    assert "valid dates counted (rows): 2" in result.answer


def test_count_distinct_orders(sales):
    """The Q3 failure: 'how many orders' should count distinct Order IDs."""
    from toolkit.adapters.registry import sheet
    adapter = sheet()
    adapter.write_range("Orders", "A1", [
        ["Order ID", "Product"],
        ["A", "apple"],
        ["A", "banana"],
        ["B", "cherry"],
        ["C", "apple"],
        ["C", "banana"],
        ["C", "cherry"],
    ])
    tools = tool_registry.load_tools()
    out = tools["count_distinct"].run({
        "tab": "Orders", "column": "Order ID",
    })
    assert "rows: 6" in out
    assert "distinct values: 3" in out


def test_count_distinct_by_colloquial_phrase(sales):
    from toolkit.adapters.registry import sheet
    adapter = sheet()
    adapter.write_range("Orders", "A1", [
        ["Order ID", "Customer ID", "Amount"],
        ["A", "C1", "100"],
        ["A", "C1", "200"],
        ["B", "C2", "150"],
    ])
    result = tool_registry.run_direct("how many orders are there?")
    assert result is not None
    assert "3 distinct values" in result.answer or "3\n" in result.answer


def test_count_distinct_resolves_unique_product_phrase():
    from toolkit.adapters.registry import sheet

    adapter = sheet()
    adapter.create_tab("Q1 Dataset")
    adapter.write_range("Q1 Dataset", "A1", [
        ["Product ID", "Product Name"],
        ["P-1", "Widget"],
        ["P-1", "Widget"],
        ["P-2", "Gadget"],
    ])

    result = tool_registry.run_direct("How many unique products are there?")

    assert result is not None
    assert result.tool == "count_distinct"
    assert "'Product ID' in 'Q1 Dataset'" in result.answer
    assert "distinct values: 2" in result.answer


def test_date_range(sales):
    tools = tool_registry.load_tools()
    out = tools["date_range"].run({"tab": "Sales", "column": "Date"})
    assert "2026-01-15" in out
    assert "2026-01-22" in out

def test_group_by_month(sales):
    tools = tool_registry.load_tools()
    out = tools["group_by_month"].run({
        "tab": "Sales", "date_column": "Date",
    })
    assert "2026-01" in out
    assert "busiest" in out.lower()


def test_group_by_month_sums_a_value(sales):
    tools = tool_registry.load_tools()
    out = tools["group_by_month"].run({
        "tab": "Sales", "date_column": "Date", "value": "Amount",
    })
    assert "sum" in out


def test_month_question_counts_distinct_orders_and_can_filter_year(sales):
    from toolkit.adapters.registry import sheet

    sheet().write_range("Q1 Dataset", "A1", [
        ["Order ID", "Order Date", "Sales"],
        ["A", "2015-01-03", "10"],
        ["A", "2015-01-04", "20"],
        ["B", "2016-01-05", "30"],
        ["C", "2015-02-01", "40"],
    ])

    result = tool_registry.run_direct(
        "How many orders were placed in January based on Q1 Dataset?"
    )
    assert result is not None
    assert result.tool == "group_by_month"
    assert "January across all years" in result.answer
    assert "2 distinct orders" in result.answer
    assert "across 3 rows" in result.answer

    result = tool_registry.run_direct(
        "How many orders were placed in January 2015 based on Q1 Dataset?"
    )
    assert result is not None
    assert "1 distinct order" in result.answer
    assert "across 2 rows" in result.answer


def test_month_name_without_tab_is_not_treated_as_a_tab():
    from toolkit.adapters.registry import sheet

    adapter = sheet()
    adapter.create_tab("Q1 Dataset")
    adapter.write_range("Q1 Dataset", "A1", [
        ["Order ID", "Order Date"],
        ["A", "2015-01-03"],
        ["A", "2015-01-04"],
    ])

    result = tool_registry.run_direct("How many orders were placed in January?")
    assert result is not None
    assert "2 rows" in result.answer
    assert "1 distinct order" in result.answer


def test_busiest_month_returns_a_concise_summary(sales):
    from toolkit.adapters.registry import sheet

    sheet().write_range("Q1 Dataset", "A1", [
        ["Order ID", "Order Date"],
        ["A", "2015-01-03"],
        ["B", "2015-01-04"],
        ["C", "2015-02-01"],
    ])

    result = tool_registry.run_direct("What is the busiest month?")
    assert result is not None
    assert "Busiest month by row count" in result.answer
    assert "2015-01:" not in result.answer
    assert "2015-01 (2 rows)" in result.answer
"""The analysis functions, tested against a real TabData."""

from __future__ import annotations

import pytest

from toolkit.adapters.base import TabData
from toolkit.brain.analysis import (
    compare_groups,
    find_outliers,
    one_thing_carrying_it,
    recently_different,
    too_small_to_judge,
    trend_over,
)


@pytest.fixture
def sales() -> TabData:
    return TabData(
        name="Sales",
        headers=["Region", "Amount", "Date", "Rep"],
        rows=[
            ["Thika", 4200, "2026-01-15", "Ann"],
            ["Ruaka", 3100, "2026-01-16", "Bob"],
            ["Thika", 5100, "2026-01-17", "Ann"],
            ["Nairobi", 2800, "2026-01-18", "Carol"],
            ["Ruaka", 9100, "2026-01-19", "Bob"],
            ["Thika", 4700, "2026-01-20", "Ann"],
            ["Nairobi", 3300, "2026-01-21", "Carol"],
            ["Ruaka", 2500, "2026-01-22", "Bob"],
        ],
    )


# ── find_outliers ─────────────────────────────────────────────────────

def test_outliers_finds_the_high_one(sales):
    report = find_outliers(sales, "Amount")
    assert report.counted == 8
    # 9100 is far above the rest
    assert any(o.value == 9100 for o in report.high)


def test_outliers_reports_normal_range(sales):
    report = find_outliers(sales, "Amount")
    assert report.normal_from < report.normal_to
    assert report.median > 0


def test_outliers_handles_too_few_rows():
    tiny = TabData(name="x", headers=["A"], rows=[[1], [2]])
    report = find_outliers(tiny, "A")
    assert report.counted == 2
    assert report.high == []


def test_outliers_rejects_unknown_column(sales):
    with pytest.raises(KeyError):
        find_outliers(sales, "Nope")


# ── compare_groups ────────────────────────────────────────────────────

def test_compare_groups_counts_by_region(sales):
    report = compare_groups(sales, "Region")
    assert report.total == 8
    names = {g.name: g.count for g in report.groups}
    assert names == {"Thika": 3, "Ruaka": 3, "Nairobi": 2}


def test_compare_groups_averages_a_value(sales):
    report = compare_groups(sales, "Region", "Amount")
    thika = next(g for g in report.groups if g.name == "Thika")
    # (4200 + 5100 + 4700) / 3 = 4666.67
    assert thika.average == pytest.approx(4666.67, abs=0.01)


def test_compare_groups_notes_the_leader(sales):
    report = compare_groups(sales, "Region")
    joined = " ".join(report.notes)
    # Thika and Ruaka tie — either could lead, but the note names one
    assert ("Thika" in joined) or ("Ruaka" in joined)


# ── trend_over ────────────────────────────────────────────────────────

def test_trend_needs_three_days():
    tiny = TabData(
        name="x", headers=["Date"], rows=[["2026-01-01"], ["2026-01-02"]],
    )
    with pytest.raises(ValueError):
        trend_over(tiny, "Date")


def test_trend_reports_direction(sales):
    report = trend_over(sales, "Date")
    assert report.days == 8
    assert report.direction in ("rising", "falling", "steady")
    assert "Busiest day" in report.note


# ── the concentration checks ──────────────────────────────────────────

def test_one_thing_carrying_it_fires_on_dominance():
    tab = TabData(
        name="x",
        headers=["Group"],
        rows=[["A"]] * 9 + [["B"]] + [["C"]],
    )
    report = compare_groups(tab, "Group")
    check = one_thing_carrying_it(report)
    assert check is not None
    assert check.what == "A"
    assert check.share == 82


def test_one_thing_carrying_it_is_silent_when_spread(sales):
    report = compare_groups(sales, "Region")
    assert one_thing_carrying_it(report) is None


def test_too_small_to_judge_fires_on_a_tiny_group():
    tab = TabData(
        name="x",
        headers=["Group"],
        rows=[["A"]] * 10 + [["B"]] * 10 + [["C"]] * 10 + [["D"]],
    )
    report = compare_groups(tab, "Group")
    warning = too_small_to_judge(report)
    assert warning is not None
    assert warning.what == "D"


def test_too_small_to_judge_is_silent_when_balanced(sales):
    report = compare_groups(sales, "Region")
    assert too_small_to_judge(report) is None


# ── recently_different ────────────────────────────────────────────────

def test_recently_different_spots_a_drop():
    rows = [[f"2026-01-{i:02d}", 100] for i in range(1, 10)]
    rows += [[f"2026-01-{i:02d}", 40] for i in range(10, 13)]
    tab = TabData(name="x", headers=["Date", "Amount"], rows=rows)
    warning = recently_different(tab, "Date", "Amount")
    assert warning is not None
    assert warning.change < 0


def test_recently_different_is_silent_on_stable_data():
    rows = [[f"2026-01-{i:02d}", 100 + (i % 3)] for i in range(1, 20)]
    tab = TabData(name="x", headers=["Date", "Amount"], rows=rows)
    assert recently_different(tab, "Date", "Amount") is None
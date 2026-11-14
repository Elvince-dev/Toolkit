"""Human-readable answers for direct tool results."""

from __future__ import annotations

from toolkit.brain import agent
from toolkit.brain.presentation import present_direct_answer
from toolkit.tools.registry import DirectResult


def test_distinct_order_result_explains_rows_vs_orders():
    raw = (
        "'Order ID' in 'Q1 Dataset':\n"
        "  distinct values: 4922\n"
        "  rows: 9800\n"
        "  average rows per value: 1.99"
    )

    answer = present_direct_answer("how many orders?", "count_distinct", raw)

    assert answer == (
        "There are 4,922 distinct orders in Q1 Dataset, represented by "
        "9,800 rows (about 1.99 rows per order)."
    )


def test_date_range_result_uses_readable_dates_and_context():
    raw = (
        "'Order Date' in 'Q1 Dataset':\n"
        "  earliest: 2015-01-03\n"
        "  latest: 2018-12-30\n"
        "  span: 1457 days (48 months)\n"
        "  valid dates counted (rows): 9800"
    )

    answer = present_direct_answer("what is the date range?", "date_range", raw)

    assert answer == (
        "The order date range in Q1 Dataset is from January 3, 2015 to "
        "December 30, 2018, spanning 1,457 days across 9,800 valid date rows."
    )


def test_summary_result_only_reports_the_requested_statistic():
    raw = (
        "'Sales' in 'Q1 Dataset':\n"
        "  count: 9800\n"
        "  sum: 2,261,536.78\n"
        "  average: 230.77\n"
        "  median: 54.49\n"
        "  min: 0.44\n"
        "  max: 22,638.48"
    )

    answer = present_direct_answer(
        "what is the median sales value?",
        "summarise_column",
        raw,
    )

    assert answer == (
        "The median Sales in Q1 Dataset is 54.49, based on 9,800 numeric values."
    )


def test_busiest_month_result_is_a_sentence():
    raw = "Busiest month by row count in 'Q1 Dataset': 2018-12 (459 rows)."

    answer = present_direct_answer("what is the busiest month?", "group_by_month", raw)

    assert answer == (
        "December 2018 was the busiest month in Q1 Dataset, with 459 rows."
    )


def test_agent_keeps_raw_evidence_but_returns_explained_answer(monkeypatch):
    raw = (
        "'Order ID' in 'Q1 Dataset':\n"
        "  distinct values: 4922\n"
        "  rows: 9800\n"
        "  average rows per value: 1.99"
    )
    monkeypatch.setattr(
        agent,
        "run_direct",
        lambda _: DirectResult(ok=True, tool="count_distinct", answer=raw),
    )

    result = agent.run_agent_sync("How many orders do we have?")

    assert "4,922 distinct orders" in result.answer
    assert result.trail[0]["result"] == raw

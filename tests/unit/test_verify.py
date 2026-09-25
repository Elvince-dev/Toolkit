"""The hallucination guards, tested against the behaviours they exist
to catch. Each test in here corresponds to a real failure that was
seen in production.
"""

from __future__ import annotations

import pytest

from toolkit.brain.verify import (
    check_claims,
    critique,
    invented_something,
    keep_the_first,
    say_how_sure,
)


# ── check_claims ──────────────────────────────────────────────────────

def test_verbatim_figure_is_supported():
    source = "Region,Amount\nThika,4200\nRuaka,3100"
    check = check_claims("Thika sold 4200", source)
    assert "4200" not in check.unsupported_numbers


def test_invented_figure_is_flagged():
    source = "Region,Amount\nThika,4200\nRuaka,3100"
    check = check_claims("Thika sold 9999", source)
    assert "9999" in check.unsupported_numbers


def test_row_count_is_derived_not_invented():
    source = "\n".join(f"row{i}" for i in range(10))
    check = check_claims("There are 10 rows", source)
    assert check.unsupported_numbers == []


def test_sum_of_source_is_derived():
    source = "100\n200\n300"
    check = check_claims("The total is 600", source)
    assert check.unsupported_numbers == []


def test_unknown_name_is_flagged():
    source = "Thika had the most complaints"
    check = check_claims("Ruaka had the most", source)
    assert "Ruaka" in check.unknown_names


def test_common_words_are_not_names():
    source = "the data shows something"
    check = check_claims("However, the Data shows Something real", source)
    # "However", "Data", "Something" are all in the stop list
    assert check.unknown_names == []


def test_clean_confidence():
    source = "A,1\nB,2"
    check = check_claims("2 rows total", source)
    assert check.clean or check.confidence in (
        "nothing to check", "every figure checks out")


# ── invented_something ────────────────────────────────────────────────

def test_invented_pipeline_is_caught():
    result = invented_something(
        "The ingestion pipeline probably dropped those rows."
    )
    assert result is not None
    assert "ingestion pipeline" in result.words


def test_real_pipeline_is_allowed_when_in_trail():
    trail = [{"tool": "describe_sheet",
              "result": "The ingestion pipeline feeds this table."}]
    result = invented_something(
        "The ingestion pipeline probably dropped those rows.",
        trail,
    )
    assert result is None


def test_plain_answer_is_not_flagged():
    assert invented_something("Thika has 4,200 in sales.") is None


def test_empty_answer_returns_none():
    assert invented_something("") is None


# ── critique ──────────────────────────────────────────────────────────

def test_how_many_without_a_number_is_flagged():
    report = critique("how many rows are there?",
                     "The data contains several categories.")
    assert not report.ok
    assert any("figure" in p for p in report.problems)


def test_which_without_a_name_is_flagged():
    report = critique("which branch is worst?", "There are differences.")
    assert not report.ok
    assert any("which" in p for p in report.problems)


def test_why_without_because_is_flagged():
    report = critique("why did sales drop?", "Sales have dropped.")
    assert not report.ok
    assert any("why" in p for p in report.problems)


def test_yes_no_with_essay_is_flagged():
    report = critique(
        "Is Ruaka in the data?",
        "The data contains several branches, and there are many "
        "ways to consider their presence, depending on how you "
        "define presence and which sheet you look at, so in some "
        "sense the answer is nuanced. " * 3,
    )
    assert not report.ok


def test_good_answer_passes():
    report = critique("how many rows?", "There are 8 rows.")
    assert report.ok
    assert report.verdict == "answers the question"


# ── keep_the_first ────────────────────────────────────────────────────

def test_refusal_loses_to_concrete_answer():
    first = "Thika has 4200 across 3 rows, averaging 1400."
    second = "NOT IN THE DATA"
    assert keep_the_first(first, second) is True


def test_buck_passing_loses_to_concrete_answer():
    first = "Thika has 4200 in the Amount column."
    second = "Please provide the data and I will calculate that."
    assert keep_the_first(first, second) is True


def test_improvement_is_accepted():
    first = "Thika has some sales."
    second = "Thika has 4200, 5100, and 4700 in sales — 14000 total."
    # second has more figures, first is vague
    assert keep_the_first(first, second) is False


def test_empty_first_means_accept_second():
    assert keep_the_first("", "answer here") is False


def test_empty_second_means_keep_first():
    assert keep_the_first("answer here", "") is True


# ── say_how_sure ──────────────────────────────────────────────────────

def test_clean_check_says_nothing():
    source = "A,1\nB,2"
    check = check_claims("2 rows", source)
    # If it happens to be clean, no sentence is needed
    if check.clean:
        assert say_how_sure(check) == ""


def test_unsupported_figure_produces_warning():
    source = "A,1"
    check = check_claims("There are 9999 rows", source)
    sentence = say_how_sure(check)
    assert "9999" in sentence
    assert sentence.startswith("\u26a0")
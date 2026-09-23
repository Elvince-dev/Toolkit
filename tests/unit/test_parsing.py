"""The canary test. If these pass, the port is faithful."""

from __future__ import annotations

from datetime import date

import pytest

from toolkit.brain.parsing import read_date, read_number


@pytest.mark.parametrize("text,expected", [
    ("1,234.5", 1234.5),
    ("KSh 2,000", 2000.0),
    ("(45)", -45.0),
    ("-45", -45.0),
    ("12%", 12.0),
    ("1.5k", 1500.0),
    ("3m", 3_000_000.0),
    ("1,2,3", None),
    ("", None),
    ("   ", None),
    ("n/a", None),
    ("hello", None),
    (12, 12.0),
    (12.5, 12.5),
    (None, None),
    (True, None),
    (False, None),
])
def test_read_number(text, expected):
    assert read_number(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("2026-01-15", date(2026, 1, 15)),
    ("2026/01/15", date(2026, 1, 15)),
    ("15/01/2026", date(2026, 1, 15)),
    ("01/15/2026", date(2026, 1, 15)),
    ("15 Jan 2026", date(2026, 1, 15)),
    ("Jan 15 2026", date(2026, 1, 15)),
    ("2026-01", date(2026, 1, 1)),
    ("01/2026", date(2026, 1, 1)),
    ("", None),
    ("not a date", None),
    ("13/13/2026", None),
    ("2026-02-30", None),
    (None, None),
])
def test_read_date(text, expected):
    assert read_date(text) == expected


def test_read_date_ambiguous_defaults_to_day_first():
    assert read_date("03/04/2026") == date(2026, 4, 3)


def test_read_date_ambiguous_month_first_when_asked():
    assert read_date("03/04/2026", order="month-first") == date(2026, 3, 4)

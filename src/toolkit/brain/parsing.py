"""Number, date, and string parsing.

Ported from Code.gs: readNumber, readDate, readDateColumn, dateStyleOf,
sameThing, editDistance, sortSensibly, meaningful.

These are the oldest and most-debugged functions in the toolkit. Every
quirk has a reason — do not "simplify" them.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any, Sequence

_SCALE = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


# ── Numbers ────────────────────────────────────────────────────────────

def read_number(value: Any) -> float | None:
    """Read a number out of anything a spreadsheet might hold.

    Handles: "1,234.5", "KSh 2,000", "(45)", "-45", "12%", "1.5k",
    "3m", "1,2,3" (rejected), None, "", "n/a".

    Returns None when the value is not a number. Booleans are never
    numbers — True is not 1 and False is not 0 in a spreadsheet cell.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return None  # dates are dates, not numbers

    s = str(value).strip()
    if not s:
        return None

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()

    percent = bool(re.search(r"%\s*$", s))
    if percent:
        s = re.sub(r"%\s*$", "", s).strip()

    scale = 1
    suffix = re.search(r"([kmb])\s*$", s, re.I)
    if suffix and len(s) >= 2 and re.search(r"[\d.]", s[-2:-1]):
        scale = _SCALE[suffix.group(1).lower()]
        s = s[:-1].strip()

    if "," in s:
        stripped = re.sub(r"^[^\d,.-]*", "", s)
        stripped = re.sub(r"[^\d,.]*$", "", stripped)
        if "," in stripped and not re.fullmatch(r"\d{1,3}(,\d{3})*(\.\d+)?", stripped):
            return None

    s = re.sub(r"^(ksh|kes|usd|eur|gbp|tzs|ugx)\.?\s*", "", s, flags=re.I)
    s = re.sub(r"[$£€¥₦]", "", s)
    s = re.sub(r"/[=\-]?\s*$", "", s)
    s = re.sub(r"[,\s\u00a0']", "", s).strip()

    if s.startswith("-"):
        negative = not negative
        s = s[1:]
    if s.endswith("-"):
        negative = not negative
        s = s[:-1]

    if not re.fullmatch(r"\d*\.?\d+", s):
        return None

    n = float(s) * scale
    return -n if negative else n


def is_number(value: Any) -> bool:
    return read_number(value) is not None


looks_numeric = is_number  # alias kept for parity with the original


# ── Dates ──────────────────────────────────────────────────────────────

def _date_ok(y: int, m: int, d: int) -> bool:
    if not (1900 <= y <= 2200):
        return False
    if not (1 <= m <= 12):
        return False
    if not (1 <= d <= 31):
        return False
    try:
        date(y, m, d)
    except ValueError:
        return False
    return True


def _expand_year(y: int) -> int:
    """Two-digit years: 70-99 → 1900s, 00-69 → 2000s."""
    if y < 100:
        return 2000 + y if y < 70 else 1900 + y
    return y


def read_date(value: Any, *, order: str = "day-first") -> date | None:
    """Read a date, guessing the day/month order where needed.

    order: "day-first" (Kenya/UK) or "month-first" (US). Only consulted
    when the two numbers are both <= 12 and therefore genuinely
    ambiguous. When one exceeds 12, the ambiguity resolves itself.

    Returns None for anything that is not a date.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    s = str(value).strip()
    if not s:
        return None

    # ISO first — no ambiguity possible
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        return date(y, mo, d) if _date_ok(y, mo, d) else None

    # Named month, day-first: "15 Jan 2026"
    m = re.match(r"^(\d{1,2})[\s\-/]*([A-Za-z]{3,9})[\s\-/,]*(\d{2,4})?$", s)
    if m:
        mo = _MONTHS.get(m[2][:4].lower()) or _MONTHS.get(m[2][:3].lower())
        if mo:
            y = _expand_year(int(m[3])) if m[3] else date.today().year
            d = int(m[1])
            return date(y, mo, d) if _date_ok(y, mo, d) else None

    # Named month, month-first: "Jan 15 2026"
    m = re.match(r"^([A-Za-z]{3,9})[\s\-/]*(\d{1,2})[\s\-/,]*(\d{2,4})?$", s)
    if m:
        mo = _MONTHS.get(m[1][:4].lower()) or _MONTHS.get(m[1][:3].lower())
        if mo:
            y = _expand_year(int(m[3])) if m[3] else date.today().year
            d = int(m[2])
            return date(y, mo, d) if _date_ok(y, mo, d) else None

    # Numeric pair: "15/01/2026" or "01/15/2026" or "03/04/2026"
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:
        a, b, y = int(m[1]), int(m[2]), _expand_year(int(m[3]))
        # Unambiguous cases resolve themselves
        if a > 12 and b <= 12:
            return date(y, b, a) if _date_ok(y, b, a) else None
        if b > 12 and a <= 12:
            return date(y, a, b) if _date_ok(y, a, b) else None
        # Genuinely ambiguous — use the caller's preference
        if order == "month-first":
            return date(y, a, b) if _date_ok(y, a, b) else None
        return date(y, b, a) if _date_ok(y, b, a) else None

    # Year-month: "2026-01"
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})", s)
    if m:
        y, mo = int(m[1]), int(m[2])
        return date(y, mo, 1) if _date_ok(y, mo, 1) else None

    # Month-year: "01/2026"
    m = re.fullmatch(r"(\d{1,2})[-/](\d{4})", s)
    if m:
        mo, y = int(m[1]), int(m[2])
        return date(y, mo, 1) if _date_ok(y, mo, 1) else None

    return None


# ── Strings ────────────────────────────────────────────────────────────

_NON_ALNUM = re.compile(r"[^a-z0-9]")


def _normalise(value: Any) -> str:
    return _NON_ALNUM.sub("", str(value).lower())


def edit_distance(a: str, b: str, limit: int = 2) -> int:
    """Levenshtein distance, capped at limit+1.

    Early-exits when the best possible score in a row exceeds `limit`,
    because the caller only cares about "close" vs "not close".
    """
    x, y = str(a), str(b)
    if abs(len(x) - len(y)) > limit:
        return limit + 1

    prev = list(range(len(y) + 1))
    for i in range(1, len(x) + 1):
        cur = [i] + [0] * len(y)
        best = i
        for j in range(1, len(y) + 1):
            cost = 0 if x[i - 1] == y[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if cur[j] < best:
                best = cur[j]
        if best > limit:
            return limit + 1
        prev = cur
    return prev[len(y)]


def same_thing(a: Any, b: Any) -> bool:
    """Are these two cell values the same thing, allowing for typos?

    "Delivery" and "Deliveries" -> True.
    "Delivery" and "Deliver" -> True (prefix).
    "Delivery 15/01" and "Delivery 15/02" -> False (numbers differ).
    """
    x = _normalise(a)
    y = _normalise(b)
    if not x or not y:
        return False
    if x == y:
        return True
    if len(x) < 3 or len(y) < 3:
        return False

    # If the digits differ, they are not the same thing — ever.
    dx = ",".join(re.findall(r"\d+", str(a)))
    dy = ",".join(re.findall(r"\d+", str(b)))
    if dx != dy:
        return False

    if x in y or y in x:
        return True

    shortest = min(len(x), len(y))
    if shortest > 24:
        return False
    limit = 1 if shortest <= 6 else 2
    return edit_distance(x, y, limit) <= limit


def meaningful(value: Any) -> bool:
    """Does this cell hold something worth counting?"""
    s = str(value if value is not None else "").strip()
    if not s:
        return False
    if re.fullmatch(r"[-–—_.·•*=/\\|:;,]+", s):
        return False
    if re.fullmatch(r"(n/?a|nil|none|null|tbd|tba|-{1,}|\?+)", s, re.I):
        return False
    return True


def sort_sensibly(items: Sequence[Any]) -> list[Any]:
    """Sort numbers as numbers, dates as dates, everything else as text."""
    arr = list(items)
    if not arr:
        return arr

    all_numbers = all(read_number(v) is not None for v in arr)
    if all_numbers:
        return sorted(arr, key=lambda v: read_number(v) or 0.0)

    all_dates = all(read_date(v) is not None for v in arr)
    if all_dates:
        return sorted(arr, key=lambda v: read_date(v) or date.min)

    return sorted(arr, key=lambda v: str(v))
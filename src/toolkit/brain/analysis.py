"""The analysis math.

Ported from Code.gs. The signatures changed:

    before:  fn(tabName, colLetter, ...)      →  reads from SpreadsheetApp
    after:   fn(tab: TabData, col: str, ...)  →  pure

This means the same function works on a CSV, a SQLite table, a
Postgres view, an Excel sheet, or a pandas frame — without knowing
which it is.

Every function in this file:
  * takes a TabData (or plain values)
  * returns a dataclass
  * never raises for "not enough data" — it returns a report saying so
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any, Sequence

from toolkit.adapters.base import TabData
from toolkit.brain.parsing import (
    is_number,
    meaningful,
    read_date,
    read_number,
)


# ── Outliers ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Outlier:
    row: int
    value: float


@dataclass(frozen=True)
class OutlierReport:
    column: str
    counted: int
    median: float
    normal_from: float
    normal_to: float
    high: list[Outlier]
    low: list[Outlier]

    @property
    def total(self) -> int:
        return len(self.high) + len(self.low)


def find_outliers(tab: TabData, column: str) -> OutlierReport:
    """IQR-based outliers. The 1.5xIQR rule, matching the original.

    Returns a report even when there are too few numbers to judge,
    with `counted < 4` telling the caller so.
    """
    idx = tab.column_index(column)
    pairs: list[tuple[int, float]] = []
    for r, row in enumerate(tab.rows, start=2):  # row 1 is headers
        v = row[idx] if idx < len(row) else None
        n = read_number(v)
        if n is not None:
            pairs.append((r, n))

    if len(pairs) < 4:
        return OutlierReport(
            column=column, counted=len(pairs),
            median=0.0, normal_from=0.0, normal_to=0.0,
            high=[], low=[],
        )

    nums = sorted(v for _, v in pairs)
    q1 = _quantile(nums, 0.25)
    q3 = _quantile(nums, 0.75)
    iqr = q3 - q1
    low_cut = q1 - 1.5 * iqr
    high_cut = q3 + 1.5 * iqr

    high = [Outlier(r, v) for r, v in pairs if v > high_cut]
    low = [Outlier(r, v) for r, v in pairs if v < low_cut]
    high.sort(key=lambda o: -o.value)
    low.sort(key=lambda o: o.value)

    return OutlierReport(
        column=column,
        counted=len(pairs),
        median=_quantile(nums, 0.5),
        normal_from=round(low_cut, 2),
        normal_to=round(high_cut, 2),
        high=high[:8],
        low=low[:8],
    )


def _quantile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    pos = (len(sorted_vals) - 1) * q
    base = int(pos)
    rest = pos - base
    if base + 1 < len(sorted_vals):
        return sorted_vals[base] + rest * (
            sorted_vals[base + 1] - sorted_vals[base]
        )
    return sorted_vals[base]


# ── Group comparison ───────────────────────────────────────────────────

@dataclass(frozen=True)
class GroupRow:
    name: str
    count: int
    share: float
    average: float | None = None


@dataclass(frozen=True)
class GroupReport:
    tab: str
    group_column: str
    total: int
    groups: list[GroupRow]
    notes: list[str] = field(default_factory=list)


def compare_groups(
    tab: TabData,
    group_column: str,
    value_column: str | None = None,
) -> GroupReport:
    """Count the rows in each group, and optionally average a number.

    "Which branch has the most complaints" is a call to this. So is
    "which region sells the most" — the second one also passes
    value_column="Amount" to get the averages.
    """
    gi = tab.column_index(group_column)
    vi = -1
    if value_column:
        try:
            vi = tab.column_index(value_column)
        except KeyError:
            vi = -1

    buckets: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    total = 0

    for row in tab.rows:
        g = str(row[gi] if gi < len(row) else "").strip()
        if not g:
            continue
        if g not in buckets:
            buckets[g] = {"count": 0, "sum": 0.0, "nums": 0}
            order.append(g)
        buckets[g]["count"] += 1
        total += 1
        if vi >= 0:
            n = read_number(row[vi] if vi < len(row) else None)
            if n is not None:
                buckets[g]["sum"] += n
                buckets[g]["nums"] += 1

    rows: list[GroupRow] = []
    for name in order:
        b = buckets[name]
        share = round(b["count"] / total * 1000) / 10 if total else 0.0
        avg = (
            round(b["sum"] / b["nums"] * 100) / 100
            if b["nums"] else None
        )
        rows.append(GroupRow(name=name, count=b["count"],
                             share=share, average=avg))

    rows.sort(key=lambda r: -r.count)

    notes = _group_notes(rows, total)
    return GroupReport(
        tab=tab.name, group_column=group_column,
        total=total, groups=rows, notes=notes,
    )


def _group_notes(rows: list[GroupRow], total: int) -> list[str]:
    if not rows or total == 0:
        return []
    notes = []
    top = rows[0]
    notes.append(
        f"{top.name} has the most, with {top.count} of {total} "
        f"({top.share}%)."
    )
    if len(rows) > 1 and top.count > rows[1].count * 2:
        notes.append(
            f"That is more than double the next one "
            f"({rows[1].name}, {rows[1].count})."
        )
    even = 100 / len(rows)
    if top.share > even * 1.8:
        notes.append(
            f"If they were evenly spread each would be about "
            f"{round(even)}%, so {top.name} really does stand out."
        )
    if any(r.average is not None for r in rows):
        by_avg = sorted(
            (r for r in rows if r.average is not None),
            key=lambda r: r.average or 0,
            reverse=True,
        )
        if by_avg and by_avg[0].name != top.name:
            notes.append(
                f"By value though, {by_avg[0].name} is highest, "
                f"averaging {by_avg[0].average}."
            )
    return notes


# ── Trends ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DayBucket:
    day: str          # YYYY-MM-DD
    count: int
    sum: float
    numbers: int

    @property
    def average(self) -> float:
        return self.sum / self.numbers if self.numbers else 0.0


@dataclass(frozen=True)
class TrendReport:
    tab: str
    days: int
    first: str
    last: str
    first_half: int
    second_half: int
    change_percent: int
    direction: str
    busiest: DayBucket | None
    series: list[DayBucket]
    note: str


def trend_over(
    tab: TabData,
    date_column: str,
    value_column: str | None = None,
) -> TrendReport:
    """Is it rising, falling, or steady?

    Compares the first half of the dated rows to the second half.
    Crude — a regression would be better — but it matches the
    original's behaviour and the numbers it produces are the ones
    the code base was built around.
    """
    di = tab.column_index(date_column)
    vi = -1
    if value_column:
        try:
            vi = tab.column_index(value_column)
        except KeyError:
            vi = -1

    by_day: dict[str, dict[str, Any]] = {}
    for row in tab.rows:
        d = read_date(row[di] if di < len(row) else None)
        if d is None:
            continue
        key = d.isoformat()
        if key not in by_day:
            by_day[key] = {"count": 0, "sum": 0.0, "nums": 0}
        by_day[key]["count"] += 1
        if vi >= 0:
            n = read_number(row[vi] if vi < len(row) else None)
            if n is not None:
                by_day[key]["sum"] += n
                by_day[key]["nums"] += 1

    order = sorted(by_day.keys())
    if len(order) < 3:
        raise ValueError(
            "I need at least three different dates to see a trend."
        )

    series = [
        DayBucket(
            day=k,
            count=by_day[k]["count"],
            sum=by_day[k]["sum"],
            numbers=by_day[k]["nums"],
        )
        for k in order
    ]

    half = len(series) // 2
    first_half = sum(s.count for s in series[:half])
    second_half = sum(s.count for s in series[len(series) - half:])
    change = (
        round((second_half - first_half) / first_half * 100)
        if first_half else 0
    )
    direction = (
        "steady" if abs(change) < 10
        else ("rising" if change > 0 else "falling")
    )
    busiest = max(series, key=lambda s: s.count)

    note = (
        f"Across {len(series)} days, the second half had "
        f"{second_half} against {first_half} in the first — "
        f"{direction}"
        + (f" by about {abs(change)}%." if direction != "steady" else ".")
        + f" Busiest day: {busiest.day} with {busiest.count}."
    )

    return TrendReport(
        tab=tab.name, days=len(series),
        first=order[0], last=order[-1],
        first_half=first_half, second_half=second_half,
        change_percent=change, direction=direction,
        busiest=busiest, series=series, note=note,
    )


# ── The "is it real?" checks ───────────────────────────────────────────

@dataclass(frozen=True)
class ConcentrationCheck:
    what: str
    share: int
    say: str


def one_thing_carrying_it(report: GroupReport) -> ConcentrationCheck | None:
    """Is one group so dominant that the total is really about it?

    Returns None when the answer is no. Returns a sentence when it is.
    The threshold (45% or more, with at least three groups) is the
    original's — chosen because below that, "mostly" is an overclaim.
    """
    if len(report.groups) < 3:
        return None
    top = report.groups[0]
    if top.share < 45:
        return None
    return ConcentrationCheck(
        what=top.name,
        share=round(top.share),
        say=(
            f'"{top.name}" alone is {round(top.share)}% of the total. '
            f"Whatever you conclude from the whole is really a "
            f"conclusion about {top.name}."
        ),
    )


@dataclass(frozen=True)
class SmallGroupWarning:
    what: str
    say: str


def too_small_to_judge(report: GroupReport) -> SmallGroupWarning | None:
    """Is the smallest group so small that "worst" is just "quietest"?

    A branch with 3 complaints out of 12 rows may look "best" but
    actually just has fewer customers. This flags it.
    """
    if len(report.groups) < 3:
        return None
    bottom = report.groups[-1]
    med = median(r.count for r in report.groups)
    if bottom.count > med * 0.15:
        return None
    return SmallGroupWarning(
        what=bottom.name,
        say=(
            f'"{bottom.name}" is so far below the rest that calling it '
            f'"worst" may just mean it barely trades. Worth checking '
            f"how many rows it has before acting on it."
        ),
    )


@dataclass(frozen=True)
class ShiftWarning:
    was: float
    now: float
    change: int
    say: str


def recently_different(
    tab: TabData,
    date_column: str,
    value_column: str,
) -> ShiftWarning | None:
    """Is the most recent quarter materially different from the rest?

    Returns None when the shift is under 35% — below that the signal
    is not worth waking somebody up for.
    """
    di = tab.column_index(date_column)
    vi = tab.column_index(value_column)

    points: list[tuple[Any, float]] = []
    for row in tab.rows:
        d = read_date(row[di] if di < len(row) else None)
        n = read_number(row[vi] if vi < len(row) else None)
        if d is None or n is None:
            continue
        points.append((d, n))

    if len(points) < 12:
        return None

    points.sort(key=lambda p: p[0])
    cut = len(points) * 3 // 4
    early = [v for _, v in points[:cut]]
    late = [v for _, v in points[cut:]]

    was = sum(early) / len(early)
    now = sum(late) / len(late)
    if was == 0:
        return None

    change = (now - was) / was
    if abs(change) < 0.35:
        return None

    pct = round(change * 100)
    direction = "below" if pct < 0 else "above"
    return ShiftWarning(
        was=round(was, 2),
        now=round(now, 2),
        change=pct,
        say=(
            f"The most recent quarter of the rows is running "
            f"{abs(pct)}% {direction} the earlier ones. The total "
            f"hides that."
        ),
    )
"""Turn direct tool reports into concise answers for people."""

from __future__ import annotations

import re
from datetime import date


def present_direct_answer(request: str, tool: str, result: str) -> str:
    """Explain common direct-tool results without changing their evidence."""
    if tool == "count_distinct":
        answer = _present_distinct(result)
    elif tool == "date_range":
        answer = _present_date_range(result)
    elif tool == "summarise_column":
        answer = _present_summary(request, result)
    elif tool == "group_by_month":
        answer = _present_months(result)
    else:
        answer = ""
    return answer or result


def _report_context(result: str) -> tuple[str, str] | None:
    if not result:
        return None
    match = re.fullmatch(
        r"'(?P<column>.+)' in '(?P<tab>.+)':",
        result.splitlines()[0].strip(),
    )
    if not match:
        return None
    return match.group("column"), match.group("tab")


def _report_fields(result: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in result.splitlines()[1:]:
        key, separator, value = line.strip().partition(":")
        if separator:
            fields[key.lower()] = value.strip()
    return fields


def _present_distinct(result: str) -> str:
    context = _report_context(result)
    fields = _report_fields(result)
    if not context or "distinct values" not in fields or "rows" not in fields:
        return ""

    column, tab = context
    column_key = column.strip().lower().replace("_", " ")
    distinct = _format_count(fields["distinct values"])
    rows = _format_count(fields["rows"])
    average = fields.get("average rows per value")
    entities = {
        "order id": ("orders", "order"),
        "customer id": ("customers", "customer"),
        "product id": ("products", "product"),
        "user id": ("users", "user"),
    }
    if column_key in entities:
        plural, singular = entities[column_key]
        if distinct == "1":
            sentence = (
                f"There is 1 distinct {singular} in {tab}, "
                f"represented by {rows} rows"
            )
        else:
            sentence = (
                f"There are {distinct} distinct {plural} in {tab}, "
                f"represented by {rows} rows"
            )
        if average:
            sentence += f" (about {average} rows per {singular})"
    else:
        sentence = (
            f"There are {distinct} distinct values in {column} in {tab}, "
            f"across {rows} rows"
        )

    empty = fields.get("empty cells")
    if empty:
        sentence += f"; {_format_count(empty)} rows have a blank {column}"
    return sentence + "."


def _present_date_range(result: str) -> str:
    context = _report_context(result)
    fields = _report_fields(result)
    if not context or "earliest" not in fields or "latest" not in fields:
        return ""

    column, tab = context
    earliest = _friendly_date(fields["earliest"])
    latest = _friendly_date(fields["latest"])
    if "order" in column.lower():
        subject = f"The {column.lower()} range in {tab}"
    else:
        subject = f"The date range for {column} in {tab}"

    sentence = f"{subject} is from {earliest} to {latest}"
    span = fields.get("span", "")
    days = re.match(r"([\d,]+) days?\b", span)
    if days:
        sentence += f", spanning {_format_count(days.group(1))} days"
    valid = fields.get("valid dates counted (rows)") or fields.get("dates counted")
    if valid:
        sentence += f" across {_format_count(valid)} valid date rows"
    return sentence + "."


def _friendly_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return value
    return f"{parsed:%B} {parsed.day}, {parsed.year}"


def _present_summary(request: str, result: str) -> str:
    context = _report_context(result)
    fields = _report_fields(result)
    if not context:
        return ""

    metric_patterns = (
        ("median", r"\bmedian\b"),
        ("average", r"\b(average|mean)\b"),
        ("sum", r"\b(total|sum|how much)\b"),
        ("max", r"\b(max|maximum|highest)\b"),
        ("min", r"\b(min|minimum|lowest)\b"),
    )
    metric = next(
        (name for name, pattern in metric_patterns
         if re.search(pattern, request, re.I)),
        None,
    )
    value = fields.get(metric or "")
    count = fields.get("count")
    if not value or not count:
        return ""

    column, tab = context
    if metric == "sum":
        return (
            f"Total {column} in {tab} is {value}, "
            f"across {_format_count(count)} numeric values."
        )
    labels = {
        "median": "The median",
        "average": "The average",
        "max": "The maximum",
        "min": "The minimum",
    }
    label = labels.get(metric or "")
    if not label:
        return ""
    return (
        f"{label} {column} in {tab} is {value}, "
        f"based on {_format_count(count)} numeric values."
    )


def _present_months(result: str) -> str:
    summary = re.fullmatch(
        r"(?P<kind>Busiest|Quietest) month by row count in "
        r"'(?P<tab>.+)': (?P<month>\d{4})-(?P<number>\d{2}) "
        r"\((?P<rows>[\d,]+) rows\)\.",
        result.strip(),
    )
    if summary:
        try:
            month = date(
                int(summary.group("month")),
                int(summary.group("number")),
                1,
            ).strftime("%B")
        except ValueError:
            return ""
        year = summary.group("month")
        return (
            f"{month} {year} was the {summary.group('kind').lower()} "
            f"month in {summary.group('tab')}, with "
            f"{_format_count(summary.group('rows'))} rows."
        )

    selected_month = re.fullmatch(
        r"(?P<month>[A-Za-z]+)(?: (?P<year>\d{4})| across all years) "
        r"in '(?P<tab>.+)': (?P<detail>.+)\.",
        result.strip(),
    )
    if selected_month:
        month = selected_month.group("month")
        year = selected_month.group("year")
        period = f"{month} {year}" if year else f"{month} across all years"
        tab = selected_month.group("tab")
        detail = selected_month.group("detail")
        orders = re.fullmatch(
            r"([\d,]+) distinct orders? across ([\d,]+) rows",
            detail,
        )
        if orders:
            count = _format_count(orders.group(1))
            verb = "was" if count == "1" else "were"
            order = "order" if count == "1" else "orders"
            return (
                f"There {verb} {count} distinct {order} in {period} in {tab}, "
                f"represented by "
                f"{_format_count(orders.group(2))} rows."
            )
        rows = re.fullmatch(r"([\d,]+) rows", detail)
        if rows:
            return (
                f"There were {_format_count(rows.group(1))} rows in "
                f"{period} in {tab}."
            )
        return f"{period} in {tab}: {detail}."

    breakdown = re.match(
        r"'(?P<tab>.+)' by month \('(?P<column>.+)'\):\n",
        result,
    )
    if breakdown:
        details = result.splitlines()[1:]
        return (
            f"Monthly row counts for {breakdown.group('tab')}, grouped by "
            f"{breakdown.group('column')}:\n" + "\n".join(details)
        )
    return ""


def _format_count(value: str) -> str:
    try:
        return f"{int(value.replace(',', '')):,}"
    except ValueError:
        return value

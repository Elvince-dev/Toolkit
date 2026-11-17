"""Tools for interacting with the calendar."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dateutil import parser as date_parser
from dateutil.tz import tzlocal
from typing import Any

from toolkit.adapters.registry import calendar
from toolkit.tools.registry import Tool, said_ok, said_no

TOOLS: dict[str, Tool] = {}

def register(tool: Tool) -> None:
    TOOLS[tool.name] = tool

def _agenda(args: dict[str, Any]) -> str:
    """List events for today or tomorrow."""
    adapter = calendar()
    if adapter is None:
        return "I have no calendar connected."

    # Default to today
    now = datetime.now(tzlocal())
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    if str(args.get("when")).lower() == "tomorrow":
        start += timedelta(days=1)
        end += timedelta(days=1)

    try:
        events = adapter.list_events(start, end)
    except Exception as exc:
        return f"I could not read your calendar: {exc}"

    if not events:
        return "You have no events scheduled."

    lines = [f"{len(events)} event(s) scheduled:"]
    for e in events:
        start_str = e.start.strftime("%H:%M")
        end_str = e.end.strftime("%H:%M")
        
        # Calculate duration
        duration_mins = int((e.end - e.start).total_seconds() / 60)
        if duration_mins >= 60:
            dur_str = f"{duration_mins // 60}h"
            if duration_mins % 60:
                dur_str += f" {duration_mins % 60}m"
        else:
            dur_str = f"{duration_mins}m"

        line = f"  · {start_str}–{end_str} ({dur_str}) — {e.title}"
        if e.join_url:
            line += f" (Meet: {e.join_url})"
        lines.append(line)
    return "\n".join(lines)

def _book_meeting(args: dict[str, Any]):
    """Create a calendar event."""
    adapter = calendar()
    if adapter is None:
        return said_no("I have no calendar connected.")

    title = str(args.get("title") or "").strip()
    when_str = str(args.get("when") or "").strip()
    
    if not title or not when_str:
        return said_no("I need a title and a time to book a meeting.")

    # Parse the natural language time
       # Parse the natural language time
    try:
        from dateutil import parser as date_parser
        from dateutil.tz import tzlocal
        import re as _re
        
        now = datetime.now(tzlocal())
        
        # Normalise common phrases
        cleaned = when_str.lower().strip()
        
        # Chop off the duration so dateutil doesn't choke on it.
        cleaned = _re.sub(r"\s+for\s+\d+\s+(hours?|minutes?|mins?)", "", cleaned)
        
        if cleaned.startswith("today"):
            cleaned = _re.sub(r"today\s*", now.strftime("%Y-%m-%d "), cleaned)
        elif cleaned.startswith("tomorrow"):
            cleaned = _re.sub(
                r"tomorrow\s*",
                (now + timedelta(days=1)).strftime("%Y-%m-%d "),
                cleaned
            )
        
        # Parse. We use `default=now` so that if the string is missing 
        # a year or time, dateutil uses today's date or current time.
        try:
            start = date_parser.parse(cleaned, default=now)
            if start.tzinfo is None:
                start = start.replace(tzinfo=tzlocal())
        except (ValueError, TypeError):
            # Fallback: today at 14:00
            start = now.replace(hour=14, minute=0, second=0, microsecond=0)
            
    except Exception as exc:
        return said_no(
            f"I could not understand the time '{when_str}'. "
            f"Try 'tomorrow at 3pm' or '2026-11-20 10:00'."
        )
    duration = int(args.get("minutes", 60))
    end = start + timedelta(minutes=duration)

    from toolkit.adapters.base import Event
    event = Event(
        id="",
        title=title,
        start=start,
        end=end,
        guests=args.get("guests", []),
    )

    try:
        created = adapter.create_event(event)
        meet_url = ""
        if args.get("with_meet", True):
            meet_url = adapter.add_meet_link(created.id)
            
        msg = f"Booked '{title}' for {start.strftime('%Y-%m-%d %H:%M')}."
        if meet_url:
            msg += f" Meet link: {meet_url}"
        return said_ok(msg)
    except Exception as exc:
        return said_no(f"Could not book meeting: {exc}")
# ── register ──────────────────────────────────────────────────────────

register(Tool(
    name="agenda",
    what="check the calendar for today or tomorrow",
    need=(),
    run=_agenda,
))

register(Tool(
    name="book_meeting",
    what="book a calendar event (needs title, when, optional minutes)",
    need=("title", "when"),
    run=_book_meeting,
))
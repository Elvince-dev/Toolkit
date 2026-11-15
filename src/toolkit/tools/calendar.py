"""Tools for interacting with the calendar."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    now = datetime.now(timezone.utc)
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
        time_str = e.start.strftime("%H:%M")
        line = f"  · {time_str} — {e.title}"
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

    # Basic parser: expects "YYYY-MM-DD HH:MM" or "today 14:00"
    try:
        now = datetime.now(timezone.utc)
        if when_str.startswith("today"):
            parts = when_str.split()
            time_parts = parts[1].split(":") if len(parts) > 1 else ["14", "00"]
            start = now.replace(hour=int(time_parts[0]), minute=int(time_parts[1]), second=0, microsecond=0)
        else:
            # Try parsing full ISO-like string
            start = datetime.strptime(when_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except Exception:
        return said_no(f"I could not understand the time '{when_str}'. Use 'YYYY-MM-DD HH:MM'.")

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
        # Try to add a Meet link automatically
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
    what="book a calendar event (needs title, when, duration)",
    need=("title", "when"),
    run=_book_meeting,
))
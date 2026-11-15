"""A fake calendar for testing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from toolkit.adapters.base import CalendarAdapter, Event


class FakeCalendarAdapter(CalendarAdapter):
    def __init__(self):
        self.events: list[Event] = []
        self.fail_create = False

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        """Return events between start and end."""
        return [
            e for e in self.events 
            if start <= e.start <= end
        ]

    def create_event(self, event: Event, *, invite: bool = True) -> Event:
        if self.fail_create:
            raise RuntimeError("Simulated create failure")
        if not event.id:
            event.id = f"evt_{len(self.events) + 1}"
        self.events.append(event)
        return event

    def add_meet_link(self, event_id: str) -> str:
        for e in self.events:
            if e.id == event_id:
                e.join_url = "https://meet.google.com/fake-link"
                return e.join_url
        raise KeyError(f"No event with id {event_id}")

    def invite(self, event_id: str, emails: list[str]) -> None:
        for e in self.events:
            if e.id == event_id:
                e.guests.extend(emails)
                return
        raise KeyError(f"No event with id {event_id}")

    def free_slots(
        self,
        start: datetime,
        end: datetime,
        *,
        minutes: int = 60,
    ) -> list[tuple[datetime, datetime]]:
        """Find free slots by looking at the day in 1-hour chunks."""
        # For the fake, we just assume everything is free between 9am and 5pm
        slots = []
        current = start.replace(hour=9, minute=0, second=0, microsecond=0)
        if current < start:
            current = start
            
        end_of_day = start.replace(hour=17, minute=0, second=0, microsecond=0)
        
        while current + timedelta(minutes=minutes) <= end_of_day:
            slot_end = current + timedelta(minutes=minutes)
            # Check if it overlaps with an existing event
            overlap = False
            for e in self.events:
                if current < e.end and slot_end > e.start:
                    overlap = True
                    break
            if not overlap:
                slots.append((current, slot_end))
            
            current += timedelta(minutes=30)
            
        return slots
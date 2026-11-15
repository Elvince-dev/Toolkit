"""The real Google Calendar adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from toolkit.adapters.base import CalendarAdapter, Event
from toolkit.brain.auth import get_credentials


class GoogleCalendarAdapter(CalendarAdapter):
    def __init__(self):
        auth = get_credentials()
        if not auth.ok or not auth.credentials:
            raise RuntimeError(f"Calendar auth failed: {auth.why}")
        
        self.service = build("calendar", "v3", credentials=auth.credentials)

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        """Fetch events from the primary calendar."""
        try:
            events_result = self.service.events().list(
                calendarId="primary",
                timeMin=start.isoformat() + "Z", # Assuming UTC for simplicity
                timeMax=end.isoformat() + "Z",
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            
            items = events_result.get("items", [])
            return [self._parse_event(item) for item in items]
        except HttpError as exc:
            raise RuntimeError(f"Calendar list failed: {exc}") from exc

    def _parse_event(self, item: dict[str, Any]) -> Event:
        start_raw = item["start"].get("dateTime") or item["start"].get("date")
        end_raw = item["end"].get("dateTime") or item["end"].get("date")
        
        # Simple ISO parse (Google usually sends RFC3339)
        start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))

        guests = [a["email"] for a in item.get("attendees", []) if "email" in a]
        join_url = item.get("hangoutLink", "")

        return Event(
            id=item["id"],
            title=item.get("summary", "(No Title)"),
            start=start,
            end=end,
            where=item.get("location", ""),
            guests=guests,
            join_url=join_url,
        )

    def create_event(self, event: Event, *, invite: bool = True) -> Event:
        """Create an event."""
        body = {
            "summary": event.title,
            "location": event.where,
            "start": {"dateTime": event.start.isoformat()},
            "end": {"dateTime": event.end.isoformat()},
            "attendees": [{"email": e} for e in event.guests] if invite else [],
        }

        try:
            created = self.service.events().insert(
                calendarId="primary", 
                body=body,
                conferenceDataVersion=1 if invite else 0
            ).execute()
            return self._parse_event(created)
        except HttpError as exc:
            raise RuntimeError(f"Calendar create failed: {exc}") from exc

    def add_meet_link(self, event_id: str) -> str:
        """Add a Google Meet link to an existing event."""
        # Note: To add a Meet link, we have to patch the event with a 
        # createRequest for conferenceData.
        import uuid
        request_id = str(uuid.uuid4())
        
        body = {
            "conferenceData": {
                "createRequest": {
                    "requestId": request_id,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"}
                }
            }
        }
        
        try:
            updated = self.service.events().patch(
                calendarId="primary", 
                eventId=event_id, 
                body=body,
                conferenceDataVersion=1
            ).execute()
            return updated.get("hangoutLink", "")
        except HttpError as exc:
            raise RuntimeError(f"Failed to add Meet link: {exc}") from exc

    def invite(self, event_id: str, emails: list[str]) -> None:
        """Add guests to an existing event."""
        # Get current attendees first so we don't overwrite them
        try:
            current = self.service.events().get(calendarId="primary", eventId=event_id).execute()
            attendees = current.get("attendees", [])
            for email in emails:
                if not any(a.get("email") == email for a in attendees):
                    attendees.append({"email": email})
                    
            self.service.events().patch(
                calendarId="primary",
                eventId=event_id,
                body={"attendees": attendees}
            ).execute()
        except HttpError as exc:
            raise RuntimeError(f"Failed to invite guests: {exc}") from exc

    def free_slots(
        self,
        start: datetime,
        end: datetime,
        *,
        minutes: int = 60,
    ) -> list[tuple[datetime, datetime]]:
        """Find free slots using the freebusy API."""
        try:
            body = {
                "timeMin": start.isoformat() + "Z",
                "timeMax": end.isoformat() + "Z",
                "items": [{"id": "primary"}]
            }
            result = self.service.freebusy().query(body=body).execute()
            busy = result["calendars"]["primary"]["busy"]
            
            # Simple algorithm: chunk the day into requested minutes
            # and check if it overlaps with any busy period.
            slots = []
            from datetime import timedelta
            
            current = start
            while current + timedelta(minutes=minutes) <= end:
                slot_end = current + timedelta(minutes=minutes)
                is_busy = False
                for b in busy:
                    b_start = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
                    b_end = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
                    if current < b_end and slot_end > b_start:
                        is_busy = True
                        break
                if not is_busy:
                    slots.append((current, slot_end))
                current += timedelta(minutes=30)
            return slots
        except HttpError as exc:
            raise RuntimeError(f"Freebusy failed: {exc}") from exc
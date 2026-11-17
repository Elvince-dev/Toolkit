from datetime import UTC, datetime, timedelta, timezone

from toolkit.adapters.base import Event
from toolkit.adapters.calendar.google import GoogleCalendarAdapter


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeEvents:
    def insert(self, *, calendarId, body, conferenceDataVersion):
        self.body = body
        return FakeRequest(
            {
                "id": "event-1",
                "summary": body["summary"],
                "start": body["start"],
                "end": body["end"],
            }
        )


class FakeService:
    def __init__(self):
        self.events_api = FakeEvents()

    def events(self):
        return self.events_api


def test_create_event_sends_consistent_utc_times():
    adapter = object.__new__(GoogleCalendarAdapter)
    adapter.service = FakeService()
    start = datetime(2026, 11, 18, 18, 0, tzinfo=timezone(timedelta(hours=3)))
    event = Event(
        id="",
        title="Timezone Test",
        start=start,
        end=start + timedelta(hours=3),
    )

    created = adapter.create_event(event)

    body = adapter.service.events_api.body
    assert datetime.fromisoformat(body["start"]["dateTime"]) == datetime(
        2026, 11, 18, 15, 0, tzinfo=UTC
    )
    assert datetime.fromisoformat(body["end"]["dateTime"]) == datetime(
        2026, 11, 18, 18, 0, tzinfo=UTC
    )
    assert body["start"]["timeZone"] == "UTC"
    assert body["end"]["timeZone"] == "UTC"
    assert created.start == datetime(2026, 11, 18, 15, 0, tzinfo=UTC)

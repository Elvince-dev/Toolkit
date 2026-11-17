import pytest
from datetime import UTC, datetime, timedelta, timezone
from toolkit.adapters.calendar.fake import FakeCalendarAdapter
from toolkit.tools import calendar as cal_tools
from toolkit.adapters.base import Event
from toolkit.tools import registry as tool_registry

@pytest.fixture
def fake_calendar(monkeypatch):
    fake = FakeCalendarAdapter()
    monkeypatch.setattr(cal_tools, "calendar", lambda: fake)
    yield fake

def test_agenda_empty(fake_calendar):
    res = cal_tools._agenda({})
    assert "no events" in res.lower()

def test_agenda_lists_events(fake_calendar):
    today = datetime.now(UTC)
    fake_calendar.events.append(Event(
        id="1", title="Test Meeting", 
        start=today, end=today, guests=[]
    ))
    res = cal_tools._agenda({})
    assert "Test Meeting" in res

def test_book_meeting(fake_calendar):
    res = cal_tools._book_meeting({
        "title": "Project Review",
        "when": "2026-11-20 10:00",
        "minutes": 30,
    })
    assert res.ok is True
    assert len(fake_calendar.events) == 1
    assert fake_calendar.events[0].title == "Project Review"


@pytest.mark.parametrize(
    ("utterance", "title", "expected_hour", "expected_minutes"),
    [
        (
            "book a meeting tomorrow called Online at 6 pm for 3 hours",
            "Online",
            18,
            180,
        ),
        (
            "book a meeting called Timezone Test for tomorrow at 12pm for 3 hours",
            "Timezone Test",
            12,
            180,
        ),
        (
            "book a meeting called Default Duration for tomorrow at 12pm",
            "Default Duration",
            12,
            60,
        ),
    ],
)
def test_book_meeting_matcher_preserves_date_time_and_duration(
    fake_calendar, monkeypatch, utterance, title, expected_hour, expected_minutes
):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 11, 17, 15, 4, 33)
            return value.replace(tzinfo=tz) if tz else value

    monkeypatch.setattr(cal_tools, "datetime", FrozenDateTime)

    result = tool_registry.run_direct(utterance)

    assert result is not None and result.ok
    event = fake_calendar.events[0]
    assert event.title == title
    assert event.start.date().isoformat() == "2026-11-18"
    assert event.start.hour == expected_hour
    assert event.start.minute == 0
    assert event.start.second == 0
    assert (event.end - event.start) == timedelta(minutes=expected_minutes)


def test_agenda_displays_google_event_in_gmt(fake_calendar):
    start_utc = (datetime.now(UTC) + timedelta(days=1)).replace(
        hour=18, minute=0, second=0, microsecond=0
    )
    event_start = start_utc.astimezone(timezone(timedelta(hours=3)))
    fake_calendar.events.append(
        Event(
            id="utc-event",
            title="Local Time",
            start=event_start,
            end=event_start + timedelta(hours=3),
            guests=[],
        )
    )

    result = cal_tools._agenda({"when": "tomorrow"})

    expected_end = start_utc + timedelta(hours=3)
    assert f"{start_utc:%H:%M}" in result
    assert f"{expected_end:%H:%M}" in result
    assert "(3h)" in result
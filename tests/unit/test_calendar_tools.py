import pytest
from datetime import datetime, timezone
from toolkit.adapters.calendar.fake import FakeCalendarAdapter
from toolkit.tools import calendar as cal_tools
from toolkit.adapters.base import Event

@pytest.fixture
def fake_calendar(monkeypatch):
    fake = FakeCalendarAdapter()
    monkeypatch.setattr(cal_tools, "calendar", lambda: fake)
    yield fake

def test_agenda_empty(fake_calendar):
    res = cal_tools._agenda({})
    assert "no events" in res.lower()

def test_agenda_lists_events(fake_calendar):
    today = datetime.now(timezone.utc)
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
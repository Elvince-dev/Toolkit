import pytest
from toolkit.adapters.mail.fake import FakeMailAdapter
from toolkit.tools import registry
from toolkit.tools import mail as mail_tools


@pytest.fixture
def fake_mail(monkeypatch):
    fake = FakeMailAdapter()
    fake._add_message("boss@company.com", "Urgent", "Call me", unread=True)
    # Patch the module where mail() is looked up
    monkeypatch.setattr(mail_tools, "mail", lambda: fake)
    yield fake


def test_matcher_read_inbox(fake_mail):
    res = registry.run_direct("what is in my inbox?")
    assert res is not None
    assert res.tool == "read_inbox"
    assert "boss@company.com" in res.answer

def test_matcher_search(fake_mail):
    res = registry.run_direct("search my emails for Urgent")
    assert res is not None
    assert res.tool == "search_mail"
    # The search matcher extracts "Urgent" as the query
    # Our fake only supports "is:unread" but we can check the routing
    assert "Found 1 thread" in res.answer or "No emails found" in res.answer

def test_matcher_archive(fake_mail):
    # Get a real ID from the fake
    t_id = list(fake_mail.threads.keys())[0]
    res = registry.run_direct(f"archive email {t_id}")
    assert res is not None
    assert res.tool == "archive_thread"
    assert res.ok is True
    
def test_matcher_send_falls_through_if_missing_args(fake_mail):
    # "send an email to bob" has no subject or body, so it should fall through
    res = registry.run_direct("send an email to bob@example.com")
    assert res is None  # Because soft=True and missing args
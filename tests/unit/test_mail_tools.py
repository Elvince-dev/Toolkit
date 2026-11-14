import pytest
from toolkit.adapters.mail.fake import FakeMailAdapter
from toolkit.tools import mail as mail_tools


@pytest.fixture
def fake_mail(monkeypatch):
    fake = FakeMailAdapter()
    fake._add_message("boss@company.com", "Urgent", "Call me", unread=True)
    fake._add_message("newsletter@spam.com", "Weekly Digest", "Hello", unread=True)

    # Patch the name *in the module that uses it*, not where it came from.
    monkeypatch.setattr(mail_tools, "mail", lambda: fake)

    yield fake


def test_read_inbox(fake_mail):
    res = mail_tools._read_inbox({})
    assert "2 unread threads" in res
    assert "boss@company.com" in res
    assert "newsletter@spam.com" in res


def test_search_mail(fake_mail):
    res = mail_tools._search_mail({"query": "is:unread"})
    assert "Found 2 thread(s)" in res


def test_send_email(fake_mail):
    res = mail_tools._send_email({
        "to": "test@example.com",
        "subject": "Hi",
        "body": "There",
    })
    assert res.ok is True
    assert "Email sent" in res.prose
    assert len(fake_mail.messages) == 3


def test_archive_thread(fake_mail):
    t_id = list(fake_mail.threads.keys())[0]
    res = mail_tools._archive_thread({"thread_id": t_id})
    assert res.ok is True
    assert fake_mail.unread_count() == 1
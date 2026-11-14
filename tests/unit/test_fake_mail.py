from toolkit.adapters.mail.fake import FakeMailAdapter

def test_unread_count():
    mail = FakeMailAdapter()
    assert mail.unread_count() == 0
    
    mail._add_message("a@b.com", "Hello", "Are you there?")
    assert mail.unread_count() == 1
    
    mail._add_message("c@d.com", "Meeting", "Let's meet")
    assert mail.unread_count() == 2

def test_search_unread():
    mail = FakeMailAdapter()
    t1 = mail._add_message("a@b.com", "Hello", "Are you there?")
    t2 = mail._add_message("c@d.com", "Meeting", "Let's meet", unread=False)
    
    results = mail.search("is:unread")
    assert len(results) == 1
    assert results[0].id == t1.id

def test_send():
    mail = FakeMailAdapter()
    mail.send(to="x@y.com", subject="Test", body="Body")
    
    # The fake adds sent messages to the "inbox" for testing purposes
    assert len(mail.messages) == 1
    assert mail.messages[0].subject == "Test"

def test_draft():
    mail = FakeMailAdapter()
    draft_id = mail.draft(to="x@y.com", subject="Test", body="Body")
    assert draft_id in mail.drafts
    assert "x@y.com" in mail.drafts[draft_id]

def test_errors():
    mail = FakeMailAdapter()
    mail.fail_send = True
    try:
        mail.send(to="x@y.com", subject="Test", body="Test")
        assert False, "Should have raised"
    except RuntimeError as e:
        assert str(e) == "Simulated send failure"
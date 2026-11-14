from toolkit.adapters.registry import mail

m = mail()
if not m:
    print("No mailbox connected.")
else:
    print(f"Unread count: {m.unread_count()}")
    print("Fetching latest 3 unread threads...")
    threads = m.search("is:unread", max_results=3)
    for t in threads:
        print(f"\nSubject: {t.subject}")
        print(f"From: {t.messages[0].sender}")
        print(f"Snippet: {t.messages[0].body[:100]}...")
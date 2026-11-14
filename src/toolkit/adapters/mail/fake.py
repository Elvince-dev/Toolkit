"""A fake mailbox for testing.

This is what proves the MailAdapter interface works before we
have to deal with the nightmare of MIME parsing, Google's API
limits, and 20MB attachment rules.

It keeps messages in memory. It can simulate delays or failures
by setting attributes on the instance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from toolkit.adapters.base import Contact, MailAdapter, Message, Thread


class FakeMailAdapter(MailAdapter):
    def __init__(self):
        self.messages: list[Message] = []
        self.threads: dict[str, Thread] = {}
        self.labels: dict[str, list[str]] = {}
        self.drafts: dict[str, str] = {}
        
        # For testing error paths
        self.fail_send = False
        self.fail_search = False

    def _add_message(
        self, sender: str, subject: str, body: str, unread: bool = True
    ) -> Thread:
        """Helper to populate the fake inbox."""
        msg_id = f"msg_{len(self.messages) + 1}"
        thread_id = f"thd_{len(self.threads) + 1}"
        
        msg = Message(
            id=msg_id,
            sender=sender,
            recipients=["me@example.com"],
            subject=subject,
            body=body,
            when=datetime.now(timezone.utc),
            unread=unread,
        )
        
        if thread_id in self.threads:
            thread = self.threads[thread_id]
            thread.messages.append(msg)
        else:
            thread = Thread(
                id=thread_id,
                subject=subject,
                messages=[msg],
                unread=unread,
            )
            self.threads[thread_id] = thread
        
        self.messages.append(msg)
        return thread

    def search(self, query: str, *, max_results: int = 25) -> list[Thread]:
        if self.fail_search:
            raise RuntimeError("Simulated search failure")
        
        # We only support "is:unread" for this fake
        results = list(self.threads.values())
        if "is:unread" in query:
            results = [t for t in results if t.unread]
            
        return results[:max_results]

    def read_thread(self, thread_id: str) -> Thread:
        if thread_id not in self.threads:
            raise KeyError(f"No thread with id {thread_id}")
        return self.threads[thread_id]

    def send(self, *, to: str, subject: str, body: str, **kw: Any) -> None:
        if self.fail_send:
            raise RuntimeError("Simulated send failure")
            
        self._add_message(
            sender="me@example.com",
            subject=subject,
            body=body,
            unread=False,
        )
        # In a real adapter, `to` would be in the message.
        # For the fake, we just want to know it was called.

    def draft(self, *, to: str, subject: str, body: str) -> str:
        draft_id = f"draft_{len(self.drafts) + 1}"
        self.drafts[draft_id] = f"To: {to}\nSubject: {subject}\n\n{body}"
        return draft_id

    def label(self, thread_id: str, label: str) -> None:
        if thread_id not in self.threads:
            raise KeyError(f"No thread with id {thread_id}")
        if thread_id not in self.labels:
            self.labels[thread_id] = []
        if label not in self.labels[thread_id]:
            self.labels[thread_id].append(label)

    def archive(self, thread_id: str) -> None:
        if thread_id not in self.threads:
            raise KeyError(f"No thread with id {thread_id}")
        # Archiving just means it's no longer unread/inbox in this fake
        self.threads[thread_id].unread = False

    def unread_count(self) -> int:
        return sum(1 for t in self.threads.values() if t.unread)
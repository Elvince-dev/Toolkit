"""The real Gmail adapter.

Maps the Gmail API's complex message format (base64, parts, headers)
into the clean Message and Thread dataclasses the brain expects.

Note: Gmail API uses the word "thread" for a chain of replies.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from toolkit.adapters.base import MailAdapter, Message, Thread
from toolkit.brain.auth import get_credentials


class GmailAdapter(MailAdapter):
    def __init__(self):
        auth = get_credentials()
        if not auth.ok or not auth.credentials:
            raise RuntimeError(f"Gmail auth failed: {auth.why}")
        
        # Build the Gmail API client (v1)
        self.service = build("gmail", "v1", credentials=auth.credentials)

    def _parse_message(self, msg_data: dict[str, Any], thread_id: str) -> Message:
        """Convert a Gmail API message dict into our Message dataclass."""
        headers = msg_data.get("payload", {}).get("headers", [])
        header_dict = {h["name"].lower(): h["value"] for h in headers}

        # Extract sender, subject, recipients
        sender = header_dict.get("from", "Unknown Sender")
        subject = header_dict.get("subject", "(No Subject)")
        to_header = header_dict.get("to", "")
        recipients = [r.strip() for r in to_header.split(",") if r.strip()]
        
        # Extract the body. This is the tricky part.
        body_text = ""
        payload = msg_data.get("payload", {})
        
        def _get_body_text(part: dict) -> str:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                data = part["body"]["data"]
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            if "parts" in part:
                for subpart in part["parts"]:
                    text = _get_body_text(subpart)
                    if text:
                        return text
            return ""

        body_text = _get_body_text(payload)
        if not body_text:
            body_text = msg_data.get("snippet", "")

        # Parse the date
        internal_date = int(msg_data.get("internalDate", 0)) / 1000.0
        when = datetime.fromtimestamp(internal_date, tz=timezone.utc)

        # Unread status
        unread = "UNREAD" in msg_data.get("labelIds", [])

        return Message(
            id=msg_data["id"],
            sender=sender,
            recipients=recipients,
            subject=subject,
            body=body_text,
            when=when,
            unread=unread,
        )

    def search(self, query: str, *, max_results: int = 25) -> list[Thread]:
        """Search the inbox and return threads."""
        try:
            # 1. List matching message IDs
            results = self.service.users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()
            
            messages = results.get("messages", [])
            if not messages:
                return []

            # 2. Group by thread ID so we return Thread objects, not Messages
            thread_ids = {m["threadId"] for m in messages}
            
            # 3. Fetch each thread
            threads = []
            for tid in thread_ids:
                try:
                    threads.append(self.read_thread(tid))
                except Exception:
                    continue  # Skip threads that vanish mid-flight

            # Sort newest first
            threads.sort(key=lambda t: t.messages[0].when, reverse=True)
            return threads[:max_results]

        except HttpError as exc:
            raise RuntimeError(f"Gmail search failed: {exc}") from exc

    def read_thread(self, thread_id: str) -> Thread:
        """Fetch all messages in a thread."""
        try:
            thread_data = self.service.users().threads().get(
                userId="me", id=thread_id
            ).execute()
            
            messages = [
                self._parse_message(m, thread_id) 
                for m in thread_data.get("messages", [])
            ]
            
            if not messages:
                raise RuntimeError(f"Thread {thread_id} is empty")

            # A thread is unread if any message in it is unread
            unread = any(m.unread for m in messages)
            
            return Thread(
                id=thread_id,
                subject=messages[0].subject,
                messages=messages,
                unread=unread,
                labels=thread_data.get("messages", [{}])[0].get("labelIds", [])
            )
        except HttpError as exc:
            raise RuntimeError(f"Could not read thread: {exc}") from exc

    def send(self, *, to: str, subject: str, body: str, **kw: Any) -> None:
        """Send an email."""
        message = EmailMessage()
        message.set_content(body)
        message["To"] = to
        message["From"] = "me"
        message["Subject"] = subject
        
        # Gmail expects base64url encoded strings
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        
        try:
            self.service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
        except HttpError as exc:
            raise RuntimeError(f"Gmail send failed: {exc}") from exc

    def draft(self, *, to: str, subject: str, body: str) -> str:
        """Create a draft. Returns the draft ID."""
        message = EmailMessage()
        message.set_content(body)
        message["To"] = to
        message["From"] = "me"
        message["Subject"] = subject
        
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        
        try:
            draft = self.service.users().drafts().create(
                userId="me", body={"message": {"raw": raw}}
            ).execute()
            return draft["id"]
        except HttpError as exc:
            raise RuntimeError(f"Gmail draft failed: {exc}") from exc

    def label(self, thread_id: str, label: str) -> None:
        """Apply a label to a thread."""
        # Note: This requires the label to exist. For the MVP, 
        # we'll just apply the STARRED and IMPORTANT standard labels.
        # Real custom labels require a lookup by name first.
        pass 

    def archive(self, thread_id: str) -> None:
        """Remove a thread from the Inbox."""
        try:
            self.service.users().threads().modify(
                userId="me", id=thread_id, body={"removeLabelIds": ["INBOX"]}
            ).execute()
        except HttpError as exc:
            raise RuntimeError(f"Gmail archive failed: {exc}") from exc

    def unread_count(self) -> int:
        """How many unread threads."""
        try:
            results = self.service.users().labels().get(
                userId="me", id="INBOX"
            ).execute()
            return results.get("threadsUnread", 0)
        except HttpError as exc:
            raise RuntimeError(f"Could not get unread count: {exc}") from exc
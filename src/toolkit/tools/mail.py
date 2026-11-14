"""Tools for interacting with email."""

from __future__ import annotations

from typing import Any

from toolkit.adapters.registry import mail
from toolkit.tools.registry import Tool, said_no, said_ok

TOOLS: dict[str, Tool] = {}

def register(tool: Tool) -> None:
    TOOLS[tool.name] = tool


def _read_inbox(args: dict[str, Any]) -> str:
    """List the most recent unread threads."""
    adapter = mail()
    if adapter is None:
        return "I have no mailbox connected. Add a Gmail token in Setup."

    try:
        # Default to 10, but allow up to 25
        limit = int(args.get("limit", 10))
        threads = adapter.search("is:unread", max_results=limit)
    except Exception as exc:
        return f"I could not read your inbox: {exc}"

    if not threads:
        return "Nothing unread. Inbox is clear."

    lines = [f"{len(threads)} unread thread{'s' if len(threads) != 1 else ''}:"]
    for i, t in enumerate(threads, 1):
        # Get the first message for sender/subject
        msg = t.messages[0]
        lines.append(f"  {i}. From: {msg.sender}")
        lines.append(f"     Subject: {msg.subject}")
        # Slice the snippet to keep it brief
        snippet = msg.body[:100].replace("\n", " ").strip()
        lines.append(f"     {snippet}...")
        lines.append(f"     [ID: {t.id}]")
        
    return "\n".join(lines)


def _search_mail(args: dict[str, Any]) -> str:
    """Search for emails using Gmail query syntax."""
    adapter = mail()
    if adapter is None:
        return "I have no mailbox connected."

    query = str(args.get("query") or "").strip()
    if not query:
        return "What should I search for?"

    try:
        threads = adapter.search(query, max_results=10)
    except Exception as exc:
        return f"The search failed: {exc}"

    if not threads:
        return f"No emails found for '{query}'."

    lines = [f"Found {len(threads)} thread(s) for '{query}':"]
    for i, t in enumerate(threads, 1):
        msg = t.messages[0]
        lines.append(f"  {i}. {msg.subject} (From: {msg.sender})")
        lines.append(f"     [ID: {t.id}]")
    return "\n".join(lines)


def _send_email(args: dict[str, Any]):
    """Send an email."""
    adapter = mail()
    if adapter is None:
        return said_no("I have no mailbox connected.")

    to = str(args.get("to") or "").strip()
    subject = str(args.get("subject") or "").strip()
    body = str(args.get("body") or "").strip()

    if not to or not subject or not body:
        return said_no("I need an address, a subject, and a body to send an email.")

    try:
        adapter.send(to=to, subject=subject, body=body)
        return said_ok(f"Email sent to {to} with subject '{subject}'.")
    except Exception as exc:
        return said_no(f"Could not send the email: {exc}")


def _archive_thread(args: dict[str, Any]):
    """Remove an email from the inbox."""
    adapter = mail()
    if adapter is None:
        return said_no("I have no mailbox connected.")

    thread_id = str(args.get("thread_id") or "").strip()
    if not thread_id:
        return said_no("Which thread should I archive? I need the ID.")

    try:
        adapter.archive(thread_id)
        return said_ok("Archived the thread.")
    except Exception as exc:
        return said_no(f"Could not archive the thread: {exc}")


# ── register ──────────────────────────────────────────────────────────

register(Tool(
    name="read_inbox",
    what="list unread emails in the inbox",
    need=(),
    run=_read_inbox,
))

register(Tool(
    name="search_mail",
    what="search emails using Gmail query syntax (e.g. 'from:boss')",
    need=("query",),
    run=_search_mail,
))

register(Tool(
    name="send_email",
    what="send an email to someone",
    need=("to", "subject", "body"),
    run=_send_email,
))

register(Tool(
    name="archive_thread",
    what="archive a thread so it leaves the inbox",
    need=("thread_id",),
    run=_archive_thread,
))
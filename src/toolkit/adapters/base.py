"""The adapter interface.

Everything the brain needs from a data source, expressed as plain
Python objects. Two kinds of adapter:

  * SheetAdapter     — required. The brain cannot work without one.
  * MailAdapter      — optional. Tools that need it raise a clear
                       error if the active adapter cannot do what is
                       asked.
  * CalendarAdapter  — optional. Same contract.

Every method returns plain data. No backend-specific objects escape
this module — the brain never sees a polars frame, a spreadsheet
range, or a sqlite row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


# ── Data shapes ────────────────────────────────────────────────────────

@dataclass
class TabData:
    """One tab of tabular data, in memory.

    This is the lingua franca of the analysis functions. Every adapter
    produces one of these; every analysis function consumes one. The
    brain never knows whether the data came from a CSV, a Postgres
    table, an Excel sheet, or a Google Sheet.
    """

    name: str
    headers: list[str]
    rows: list[list[Any]]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return len(self.headers)

    def column_index(self, name: str) -> int:
        """Find a column by name. Exact match first, then substring.

        Case-insensitive. Raises KeyError if nothing matches — the
        caller should catch and turn it into a human sentence.
        """
        low = name.strip().lower()
        for i, h in enumerate(self.headers):
            if h.strip().lower() == low:
                return i
        for i, h in enumerate(self.headers):
            hl = h.strip().lower()
            if low in hl or hl in low:
                return i
        raise KeyError(
            f"No column named {name!r} "
            f"(have: {', '.join(self.headers[:8])}"
            f"{'...' if len(self.headers) > 8 else ''})"
        )

    def has_column(self, name: str) -> bool:
        try:
            self.column_index(name)
            return True
        except KeyError:
            return False

    def column(self, name: str) -> list[Any]:
        """Every value in a named column, in row order."""
        i = self.column_index(name)
        return [row[i] if i < len(row) else None for row in self.rows]


@dataclass
class Selection:
    """What the user had highlighted, when the backend supports it.

    A CSV folder has no notion of "highlighted cells". A Google Sheet
    does. Adapters that cannot provide this return None, and the tools
    that require it say so clearly rather than crashing.
    """

    tab: str
    a1: str
    values: list[list[Any]]


@dataclass
class Message:
    id: str
    sender: str
    recipients: list[str]
    subject: str
    body: str
    when: datetime
    unread: bool = False


@dataclass
class Thread:
    id: str
    subject: str
    messages: list[Message]
    unread: bool = False
    labels: list[str] = field(default_factory=list)


@dataclass
class Event:
    id: str
    title: str
    start: datetime
    end: datetime
    where: str = ""
    guests: list[str] = field(default_factory=list)
    join_url: str = ""


@dataclass
class Contact:
    name: str
    email: str
    phone: str = ""
    role: str = ""
    company: str = ""
    source: str = ""


# ── Interfaces ─────────────────────────────────────────────────────────

@runtime_checkable
class SheetAdapter(Protocol):
    """The one adapter the brain cannot do without.

    `runtime_checkable` lets us write `isinstance(x, SheetAdapter)` for
    diagnostics. It only checks that the methods exist; it does not
    check signatures. That is fine — the tests check the behaviour.
    """

    # Required ────────────────────────────────────────────────────────

    def list_tabs(self) -> list[str]:
        """Every tab name, in a stable order."""
        ...

    def read_tab(self, name: str, *, sample: int = 300) -> TabData:
        """Read one tab into memory.

        `sample` caps how many rows are loaded. The brain uses 300 by
        default — enough to reason about, small enough to be fast.
        Adapters may return fewer rows than exist; `row_count` reflects
        what was actually read, not what is on disk.
        """
        ...

    def write_range(
        self, tab: str, a1: str, values: list[list[Any]]
    ) -> None:
        """Write a rectangle of cells at an A1 anchor like 'B3'."""
        ...

    def append_rows(self, tab: str, rows: list[list[Any]]) -> None:
        """Add rows to the bottom of a tab."""
        ...

    def create_tab(self, name: str) -> None:
        ...

    def delete_tab(self, name: str) -> None:
        ...

    def get_user(self) -> dict[str, str]:
        """Who is running this. Keys: name, email, timezone.

        Adapters that cannot identify a user return placeholders.
        """
        ...

    # Optional ────────────────────────────────────────────────────────
    # Implementations should raise NotImplementedError for anything
    # they cannot do, and the tools that need it will catch and explain.

    def current_selection(self) -> Selection | None:
        """The cells the user has highlighted, or None.

        Backends without a UI (CSV, Postgres) return None.
        """
        raise NotImplementedError

    def get_cell_note(self, tab: str, a1: str) -> str:
        raise NotImplementedError

    def set_cell_note(self, tab: str, a1: str, note: str) -> None:
        raise NotImplementedError


@runtime_checkable
class MailAdapter(Protocol):
    """Optional. Tools that need it check for its presence first."""

    def search(self, query: str, *, max_results: int = 25) -> list[Thread]:
        ...

    def read_thread(self, thread_id: str) -> Thread:
        ...

    def send(
        self, *, to: str, subject: str, body: str, **kw: Any
    ) -> None:
        ...

    def draft(self, *, to: str, subject: str, body: str) -> str:
        """Create a draft. Returns the draft id."""
        ...

    def label(self, thread_id: str, label: str) -> None:
        ...

    def archive(self, thread_id: str) -> None:
        ...

    def unread_count(self) -> int:
        ...


@runtime_checkable
class CalendarAdapter(Protocol):
    """Optional. Tools that need it check for its presence first."""

    def list_events(
        self, start: datetime, end: datetime
    ) -> list[Event]:
        ...

    def create_event(
        self, event: Event, *, invite: bool = True
    ) -> Event:
        ...

    def add_meet_link(self, event_id: str) -> str:
        ...

    def invite(self, event_id: str, emails: list[str]) -> None:
        ...

    def free_slots(
        self,
        start: datetime,
        end: datetime,
        *,
        minutes: int = 60,
    ) -> list[tuple[datetime, datetime]]:
        ...
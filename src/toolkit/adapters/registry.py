"""Picks the right adapter from settings.

One place, so nothing else has to know how adapters are wired. The
result is cached — a test that changes settings must call reset().
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Iterator

from toolkit.adapters.base import CalendarAdapter, MailAdapter, SheetAdapter
from toolkit.config import settings

_request_sheet: ContextVar[SheetAdapter | None] = ContextVar(
    "toolkit_request_sheet",
    default=None,
)


@lru_cache(maxsize=1)
def _default_sheet() -> SheetAdapter:
    name = settings().sheet_adapter
    if name == "csv":
        from toolkit.adapters.sheets.csv_folder import CsvFolderAdapter
        return CsvFolderAdapter(settings().csv_path)  # type: ignore[return-value]
    if name == "sqlite":
        from toolkit.adapters.sheets.sqlite import SqliteAdapter
        return SqliteAdapter(settings().sqlite_path)  # type: ignore[return-value]
    if name == "postgres":
        from toolkit.adapters.sheets.postgres import PostgresAdapter
        if not settings().pg_dsn:
            raise RuntimeError("TOOLKIT_PG_DSN is not set")
        return PostgresAdapter(settings().pg_dsn)  # type: ignore[return-value]
    if name == "excel":
        from toolkit.adapters.sheets.excel import ExcelAdapter
        return ExcelAdapter(settings().data_dir / "workbook.xlsx")  # type: ignore[return-value]
    if name == "google":
        from toolkit.adapters.sheets.google_sheets import GoogleSheetsAdapter
        return GoogleSheetsAdapter()  # type: ignore[return-value]
    raise ValueError(f"Unknown sheet adapter: {name!r}")


def sheet() -> SheetAdapter:
    """Return the request-scoped adapter, or the configured default."""
    return _request_sheet.get() or _default_sheet()


@contextmanager
def using_sheet_adapter(adapter: SheetAdapter) -> Iterator[None]:
    token = _request_sheet.set(adapter)
    try:
        yield
    finally:
        _request_sheet.reset(token)


@lru_cache(maxsize=1)
def mail():
    """Return the configured MailAdapter, or None if not set up."""
    from toolkit.config import settings
    
    token_path = settings().data_dir / "token.json"
    if not token_path.exists():
        return None

    try:
        from toolkit.adapters.mail.gmail import GmailAdapter
        return GmailAdapter()
    except Exception as e:
        import logging
        logging.warning(f"Could not load Gmail adapter: {e}")
        return None

@lru_cache(maxsize=1)
def calendar():
    """Return the configured CalendarAdapter, or None."""
    from toolkit.config import settings
    token_path = settings().data_dir / "token.json"
    if not token_path.exists():
        return None

    try:
        from toolkit.adapters.calendar.google import GoogleCalendarAdapter
        return GoogleCalendarAdapter()
    except Exception as e:
        import logging
        logging.warning(f"Could not load Calendar adapter: {e}")
        return None

@lru_cache(maxsize=1)
def mail():
    """Return the configured MailAdapter, or None if not set up."""
    # For now, we always return the real Gmail adapter if a token exists.
    from toolkit.config import settings
    
    token_path = settings().data_dir / "token.json"
    if not token_path.exists():
        return None

    try:
        from toolkit.adapters.mail.gmail import GmailAdapter
        return GmailAdapter()
    except Exception as e:
        # If auth fails (e.g., bad token), return None.
        # The tools will say "no mailbox".
        import logging
        logging.warning(f"Could not load Gmail adapter: {e}")
        return None
        
def reset() -> None:
    """Clear cached adapters. Tests call this when settings change."""
    _default_sheet.cache_clear()
    mail.cache_clear()
    calendar.cache_clear()
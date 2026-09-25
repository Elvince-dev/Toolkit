"""Picks the right adapter from settings.

One place, so nothing else has to know how adapters are wired. The
result is cached — a test that changes settings must call reset().
"""

from __future__ import annotations

from functools import lru_cache

from toolkit.adapters.base import CalendarAdapter, MailAdapter, SheetAdapter
from toolkit.config import settings


@lru_cache(maxsize=1)
def sheet() -> SheetAdapter:
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


@lru_cache(maxsize=1)
def mail() -> MailAdapter | None:
    name = settings().mail_adapter
    if name == "fake":
        from toolkit.adapters.mail.fake import FakeMailAdapter
        return FakeMailAdapter()  # type: ignore[return-value]
    if name == "gmail":
        from toolkit.adapters.mail.gmail import GmailAdapter
        return GmailAdapter()  # type: ignore[return-value]
    if name == "imap":
        from toolkit.adapters.mail.imap import ImapAdapter
        return ImapAdapter()  # type: ignore[return-value]
    return None


@lru_cache(maxsize=1)
def calendar() -> CalendarAdapter | None:
    name = settings().calendar_adapter
    if name == "fake":
        from toolkit.adapters.calendar.fake import FakeCalendarAdapter
        return FakeCalendarAdapter()  # type: ignore[return-value]
    if name == "google":
        from toolkit.adapters.calendar.google import GoogleCalendarAdapter
        return GoogleCalendarAdapter()  # type: ignore[return-value]
    if name == "caldav":
        from toolkit.adapters.calendar.caldav import CalDavAdapter
        return CalDavAdapter()  # type: ignore[return-value]
    return None


def reset() -> None:
    """Clear cached adapters. Tests call this when settings change."""
    sheet.cache_clear()
    mail.cache_clear()
    calendar.cache_clear()
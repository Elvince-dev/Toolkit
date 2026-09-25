"""Settings, loaded from environment and .env.

One place, so nothing else has to know how the pieces are wired.
Everything has a sensible default for local development; nothing
requires a value that would break a first-run experience.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

SheetAdapterName = Literal["csv", "sqlite", "postgres", "excel", "google"]
MailAdapterName = Literal["gmail", "imap", "fake"]
CalendarAdapterName = Literal["google", "caldav", "fake"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TOOLKIT_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "dev"
    log_level: str = "INFO"
    data_dir: Path = Path("./data")

    sheet_adapter: SheetAdapterName = "csv"
    mail_adapter: MailAdapterName = "fake"
    calendar_adapter: CalendarAdapterName = "fake"

    csv_path: Path = Path("./data/csv")
    sqlite_path: Path = Path("./data/toolkit.db")
    pg_dsn: str | None = None

    google_credentials: Path | None = None
    google_token: Path | None = None

    telegram_token: str | None = None
    telegram_chat: str | None = None

    host: str = "127.0.0.1"
    port: int = 8000
    secret_key: str = "change-me"

    domain_preset: str = "generic"
    domain_file: Path | None = None


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
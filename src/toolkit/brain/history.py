"""Lightweight conversation history.

Stored in a SQLite table so the agent can remember what happened
across separate CLI invocations.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from toolkit.config import settings

@dataclass
class Turn:
    role: str  # "user" or "assistant"
    text: str

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""

@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    path = settings().data_dir / "history.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()

def load_recent(limit: int = 10) -> list[Turn]:
    """Load the last N turns, oldest first."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT role, text FROM turns ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    
    # We queried descending to get the *most recent*, now reverse
    # so they are in chronological order for the LLM.
    return [Turn(role=r["role"], text=r["text"]) for r in reversed(rows)]

def save_turn(role: str, text: str) -> None:
    """Append one turn to the history."""
    with _db() as conn:
        conn.execute(
            "INSERT INTO turns (role, text, created_at) VALUES (?, ?, ?)",
            (role, text, time.time())
        )

def clear() -> None:
    """Wipe the history."""
    with _db() as conn:
        conn.execute("DELETE FROM turns")
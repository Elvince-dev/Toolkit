"""Shared result shapes for brain modules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AuthResult:
    """The outcome of an authentication attempt.

    ok: True if we have a valid, usable token.
    why: A human-readable reason if ok is False.
    credentials: The google.oauth2.credentials.Credentials object.
    """
    ok: bool
    why: str = ""
    credentials: object | None = None
"""Google OAuth: loading, saving, refreshing, and consent.

The brain does not know how to send email. It knows how to ask
for an OAuth token. The Gmail and Calendar adapters then use that
token to build their API clients.

This module handles the "first time" consent flow (opening a browser)
and the "normal" refresh flow (silent, no browser).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from toolkit.brain.results import AuthResult
from toolkit.config import settings

# If you change these, users must delete data/token.json.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/contacts.readonly",
]


def get_credentials() -> AuthResult:
    """Load, refresh, or acquire Google credentials.

    Order of operations:
      1. Check for a cached token file (data/token.json).
      2. If found and valid, return it.
      3. If found but expired, refresh it silently.
      4. If missing or refresh fails, start the browser consent flow.
    """
    data_dir = settings().data_dir
    token_path = data_dir / "token.json"
    creds_path = data_dir / "credentials.json"

    creds: Credentials | None = None

    # 1. Try to load the existing token
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(
                str(token_path), SCOPES
            )
        except Exception as exc:
            # Corrupt token file. We'll fall through to the consent flow.
            pass

    # 2. If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # 3. Try to refresh silently
            try:
                creds.refresh(Request())
            except Exception as exc:
                return AuthResult(
                    ok=False,
                    why=f"Could not refresh Google token: {exc}. "
                        f"Delete {token_path.name} to log in again."
                )
        else:
            # 4. First-time consent flow
            if not creds_path.exists():
                return AuthResult(
                    ok=False,
                    why=(
                        f"Missing {creds_path.name}. Download it from the "
                        f"Google Cloud Console and save it in {data_dir}."
                    )
                )
            
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(creds_path), SCOPES
                )
                # This opens the browser and starts a local server to catch the redirect
                creds = flow.run_local_server(port=0)
            except Exception as exc:
                return AuthResult(
                    ok=False,
                    why=f"Login failed: {exc}"
                )

        # 5. Save the credentials for the next run
        try:
            token_path.write_text(creds.to_json(), encoding="utf-8")
        except Exception as exc:
            return AuthResult(
                ok=False,
                why=f"Authenticated, but could not save token: {exc}"
            )

    return AuthResult(ok=True, credentials=creds)
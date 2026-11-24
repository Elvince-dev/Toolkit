from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import HTTPException

from api import main


class SupabaseAuthClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.request: tuple[str, dict[str, str]] | None = None

    async def __aenter__(self) -> SupabaseAuthClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, url: str, *, headers: dict[str, str]) -> httpx.Response:
        self.request = (url, headers)
        return self.response


def test_current_user_uses_supabase_to_validate_bearer_token(monkeypatch):
    client = SupabaseAuthClient(
        httpx.Response(200, json={"id": "verified-user-id"})
    )
    monkeypatch.setattr(
        main,
        "settings",
        lambda: type(
            "Config",
            (),
            {
                "supabase_url": "https://project.supabase.co/",
                "supabase_publishable_key": "publishable-key",
            },
        )(),
    )
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **_: client)

    user = asyncio.run(main.get_current_user("Bearer verified-access-token"))

    assert user.id == "verified-user-id"
    assert user.access_token == "verified-access-token"
    assert client.request == (
        "https://project.supabase.co/auth/v1/user",
        {
            "apikey": "publishable-key",
            "Authorization": "Bearer verified-access-token",
        },
    )


def test_current_user_rejects_missing_bearer_token():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main.get_current_user(None))

    assert exc_info.value.status_code == 401


def test_current_user_rejects_token_supabase_does_not_accept(monkeypatch):
    client = SupabaseAuthClient(httpx.Response(401, json={"message": "invalid"}))
    monkeypatch.setattr(
        main,
        "settings",
        lambda: type(
            "Config",
            (),
            {
                "supabase_url": "https://project.supabase.co",
                "supabase_publishable_key": "publishable-key",
            },
        )(),
    )
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **_: client)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main.get_current_user("Bearer invalid-token"))

    assert exc_info.value.status_code == 401

"""Supabase REST and Storage access using the authenticated user's token."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from toolkit.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    access_token: str


class SupabaseUserClient:
    def __init__(self, config: Settings, user: AuthenticatedUser) -> None:
        if not config.supabase_url or not config.supabase_publishable_key:
            raise HTTPException(
                status_code=503,
                detail="Supabase is not configured on the API.",
            )
        self.base_url = config.supabase_url.rstrip("/")
        self.publishable_key = config.supabase_publishable_key
        self.access_token = user.access_token

    async def rest(
        self,
        method: str,
        table: str,
        *,
        params: dict[str, str] | None = None,
        body: object | None = None,
        prefer: str | None = None,
    ) -> object:
        headers = {}
        if prefer:
            headers["Prefer"] = prefer
        response = await self._request(
            method,
            f"/rest/v1/{table}",
            params=params,
            json=body,
            headers=headers,
        )
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail="Supabase returned an invalid database response.",
            ) from exc

    async def upload(
        self,
        path: str,
        content: bytes,
        *,
        upsert: bool = False,
    ) -> None:
        await self._request(
            "POST",
            f"/storage/v1/object/datasets/{quote(path, safe='/')}",
            content=content,
            headers={
                "Content-Type": "text/csv",
                "x-upsert": str(upsert).lower(),
            },
        )

    async def download(self, path: str) -> bytes:
        response = await self._request(
            "GET",
            f"/storage/v1/object/datasets/{quote(path, safe='/')}",
        )
        return response.content

    async def delete(self, path: str) -> None:
        await self._request(
            "DELETE",
            "/storage/v1/object/datasets",
            json={"prefixes": [path]},
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: object | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        endpoint = _safe_endpoint(path)
        request_headers = {
            "apikey": self.publishable_key,
            "Authorization": f"Bearer {self.access_token}",
        }
        if headers:
            request_headers.update(headers)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    params=params,
                    json=json,
                    content=content,
                    headers=request_headers,
                )
        except httpx.RequestError as exc:
            logger.warning(
                "Supabase request %s %s failed (%s).",
                method,
                endpoint,
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=503,
                detail="Could not reach Supabase.",
            ) from exc

        if response.is_error:
            status_code = response.status_code
            logger.warning(
                "Supabase request %s %s returned HTTP %s.",
                method,
                endpoint,
                status_code,
            )
            if status_code == 400:
                raise HTTPException(
                    status_code=502,
                    detail="Supabase rejected the requested data operation.",
                )
            if status_code in (401, 403, 404, 409, 413):
                raise HTTPException(
                    status_code=status_code,
                    detail="Supabase rejected the requested data operation.",
                )
            raise HTTPException(
                status_code=503,
                detail="Supabase could not complete the data operation.",
            )
        return response


def _safe_endpoint(path: str) -> str:
    path = path.split("?", 1)[0]
    if path.startswith("/rest/v1/"):
        table = path.removeprefix("/rest/v1/").split("/", 1)[0]
        return f"/rest/v1/{table}"
    if path.startswith("/storage/v1/object/"):
        bucket = path.removeprefix("/storage/v1/object/").split("/", 1)[0]
        return f"/storage/v1/object/{bucket}"
    return path

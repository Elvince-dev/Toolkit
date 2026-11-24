from __future__ import annotations

import asyncio
from io import BytesIO

from fastapi import UploadFile

from api import main
from api.supabase import AuthenticatedUser

USER_ID = "00000000-0000-0000-0000-000000000001"


class UploadClient:
    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}
        self.dataset_body: dict[str, object] | None = None

    async def upload(self, path: str, content: bytes, *, upsert: bool = False) -> None:
        assert not upsert
        self.uploaded[path] = content

    async def rest(self, method: str, table: str, **kwargs: object) -> object:
        assert (method, table) == ("POST", "datasets")
        body = kwargs["body"]
        assert isinstance(body, dict)
        self.dataset_body = body
        return [{**body, "created_at": "2026-01-01T00:00:00Z"}]


def test_upload_stores_csv_under_authenticated_user_and_returns_dataset(monkeypatch):
    client = UploadClient()
    user = AuthenticatedUser(id=USER_ID, access_token="test-token")
    monkeypatch.setattr(main, "_client", lambda authenticated_user: client)
    upload = UploadFile(
        filename="Quarter 1.csv",
        file=BytesIO(b"Month,Sales\nJanuary,120\nFebruary,180\n"),
    )

    result = asyncio.run(main.upload_file(upload, user))

    assert result["name"] == "Quarter 1"
    assert result["row_count"] == 2
    assert result["storage_path"].startswith(f"{USER_ID}/")
    assert client.uploaded[result["storage_path"]].startswith(b"Month,Sales")
    assert client.dataset_body["user_id"] == USER_ID

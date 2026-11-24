from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from api import main
from api.supabase import AuthenticatedUser
from toolkit.adapters.registry import sheet
from toolkit.brain.history import Turn

USER_ID = "00000000-0000-0000-0000-000000000001"
DATASET_ID = UUID("00000000-0000-0000-0000-000000000002")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000003")
USER = AuthenticatedUser(id=USER_ID, access_token="test-token")


def test_owned_dataset_query_is_scoped_to_user_and_hides_missing_data():
    class MissingDatasetClient:
        params: dict[str, str] | None = None

        async def rest(self, method: str, table: str, *, params: dict[str, str]):
            assert (method, table) == ("GET", "datasets")
            self.params = params
            return []

    client = MissingDatasetClient()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(main._owned_dataset(client, USER, DATASET_ID))

    assert exc_info.value.status_code == 404
    assert client.params["user_id"] == f"eq.{USER_ID}"


def test_chat_uses_selected_users_csv_and_persists_conversation_history(monkeypatch):
    csv_content = b"Month,Sales\nJanuary,120\n"
    previous_messages = [
        {
            "id": "message-id",
            "role": "user",
            "content": "Earlier question",
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]

    class ChatClient:
        saved_messages: list[dict[str, object]] | None = None

        async def rest(self, method: str, table: str, *, params=None, body=None, **kwargs):
            if method == "GET" and table == "conversations":
                return [{
                    "id": str(CONVERSATION_ID),
                    "user_id": USER_ID,
                    "dataset_id": str(DATASET_ID),
                    "title": "New conversation",
                }]
            if method == "GET" and table == "datasets":
                return [{
                    "id": str(DATASET_ID),
                    "user_id": USER_ID,
                    "name": "Forecast",
                    "storage_path": f"{USER_ID}/{DATASET_ID}.csv",
                    "row_count": 1,
                }]
            if method == "GET" and table == "messages":
                return previous_messages.copy()
            if method == "POST" and table == "messages":
                self.saved_messages = body
                return None
            if method == "PATCH" and table == "conversations":
                return None
            raise AssertionError(f"Unexpected Supabase request: {method} {table}")

        async def download(self, path: str) -> bytes:
            assert path == f"{USER_ID}/{DATASET_ID}.csv"
            return csv_content

    client = ChatClient()
    agent_call: dict[str, object] = {}
    monkeypatch.setattr(main, "_client", lambda user: client)

    async def fake_run_agent(message: str, **kwargs: object):
        tab = sheet().read_tab("Forecast")
        agent_call["message"] = message
        agent_call["kwargs"] = kwargs
        agent_call["rows"] = tab.rows
        return SimpleNamespace(
            answer="Sales are 120.",
            why="",
            trail=[{"tool": "read_sheet"}],
        )

    monkeypatch.setattr(main, "run_agent", fake_run_agent)
    request = main.ChatRequest(
        message="What were sales?",
        conversation_id=CONVERSATION_ID,
        dataset_id=DATASET_ID,
    )

    response = asyncio.run(main.chat_endpoint(request, USER))

    assert response.answer == "Sales are 120."
    assert response.conversation_id == CONVERSATION_ID
    assert agent_call["rows"] == [["January", "120"]]
    assert agent_call["kwargs"]["history"] == [Turn("user", "Earlier question")]
    assert agent_call["kwargs"]["persist_history"] is False
    assert len(client.saved_messages) == 2
    assert set(client.saved_messages[0]) == set(client.saved_messages[1])
    assert client.saved_messages[0]["role"] == "user"
    assert client.saved_messages[1]["role"] == "assistant"

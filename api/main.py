import csv
import io
import logging
import re
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.supabase import AuthenticatedUser, SupabaseUserClient
from toolkit.adapters.registry import using_sheet_adapter
from toolkit.adapters.sheets.csv_folder import CsvFolderAdapter
from toolkit.brain.agent import run_agent
from toolkit.brain.history import Turn
from toolkit.config import settings

logger = logging.getLogger(__name__)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings().frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    conversation_id: UUID
    dataset_id: UUID


class ChatResponse(BaseModel):
    answer: str
    tool_used: str | None = None
    conversation_id: UUID


class ConversationCreate(BaseModel):
    dataset_id: UUID
    title: str = Field(default="New conversation", min_length=1, max_length=120)


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    scheme, separator, token = (authorization or "").partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    config = settings()
    if not config.supabase_url or not config.supabase_publishable_key:
        raise HTTPException(
            status_code=503,
            detail="Supabase authentication is not configured on the API.",
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{config.supabase_url.rstrip('/')}/auth/v1/user",
                headers={
                    "apikey": config.supabase_publishable_key,
                    "Authorization": f"Bearer {token.strip()}",
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not verify your session with Supabase.",
        ) from exc

    if response.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    if response.status_code != 200:
        raise HTTPException(
            status_code=503,
            detail="Supabase could not verify your session.",
        )

    try:
        user_id = response.json().get("id")
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Supabase returned an invalid session response.",
        ) from exc
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Invalid session.")
    return AuthenticatedUser(id=user_id, access_token=token.strip())


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


def _client(user: AuthenticatedUser) -> SupabaseUserClient:
    return SupabaseUserClient(settings(), user)


def _rows(value: object, *, operation: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise HTTPException(
            status_code=502,
            detail=f"Supabase returned an invalid response for {operation}.",
        )
    return value


async def _owned_dataset(
    client: SupabaseUserClient,
    user: AuthenticatedUser,
    dataset_id: UUID,
) -> dict[str, Any]:
    rows = _rows(
        await client.rest(
            "GET",
            "datasets",
            params={
                "select": "id,user_id,name,storage_path,row_count,created_at",
                "id": f"eq.{dataset_id}",
                "user_id": f"eq.{user.id}",
                "limit": "1",
            },
        ),
        operation="dataset lookup",
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    dataset = rows[0]
    if not str(dataset.get("storage_path", "")).startswith(f"{user.id}/"):
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return dataset


async def _owned_conversation(
    client: SupabaseUserClient,
    user: AuthenticatedUser,
    conversation_id: UUID,
) -> dict[str, Any]:
    rows = _rows(
        await client.rest(
            "GET",
            "conversations",
            params={
                "select": "id,user_id,dataset_id,title",
                "id": f"eq.{conversation_id}",
                "user_id": f"eq.{user.id}",
                "limit": "1",
            },
        ),
        operation="conversation lookup",
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return rows[0]


def _safe_dataset_name(filename: str | None) -> str:
    raw_name = Path((filename or "dataset").replace("\\", "/")).stem
    name = re.sub(r"[^A-Za-z0-9 _.-]", "_", raw_name)
    name = re.sub(r"^[^A-Za-z0-9]+", "", name).strip(" .")[:100]
    return name or "dataset"


def _csv_row_count(content: bytes) -> int:
    try:
        reader = csv.reader(io.StringIO(content.decode("utf-8-sig"), newline=""))
        headers = next(reader, None)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise HTTPException(status_code=400, detail="The uploaded CSV is invalid.") from exc
    if not headers:
        raise HTTPException(status_code=400, detail="The CSV must include a header row.")
    try:
        return sum(1 for _ in reader)
    except csv.Error as exc:
        raise HTTPException(status_code=400, detail="The uploaded CSV is invalid.") from exc


def _read_csv(content: bytes, name: str, sample: int):
    with tempfile.TemporaryDirectory(prefix="toolkit-dataset-") as directory:
        path = Path(directory) / f"{name}.csv"
        path.write_bytes(content)
        return CsvFolderAdapter(directory).read_tab(name, sample=sample)


async def _get_messages(
    client: SupabaseUserClient,
    user: AuthenticatedUser,
    conversation_id: UUID,
) -> list[dict[str, Any]]:
    return _rows(
        await client.rest(
            "GET",
            "messages",
            params={
                "select": "id,role,content,tool_used,created_at",
                "conversation_id": f"eq.{conversation_id}",
                "user_id": f"eq.{user.id}",
                "order": "created_at.asc",
                "limit": "1000",
            },
        ),
        operation="conversation history",
    )


@app.get("/api/datasets")
async def list_datasets(user: CurrentUser):
    rows = _rows(
        await _client(user).rest(
            "GET",
            "datasets",
            params={
                "select": "id,name,row_count,created_at",
                "user_id": f"eq.{user.id}",
                "order": "created_at.desc",
            },
        ),
        operation="dataset list",
    )
    return {"datasets": rows}


@app.post("/api/upload")
async def upload_file(
    file: Annotated[UploadFile, File()],
    user: CurrentUser,
):
    if not file.filename or Path(file.filename.replace("\\", "/")).suffix.lower() != ".csv":
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    content = await file.read()
    row_count = _csv_row_count(content)
    dataset_id = uuid.uuid4()
    storage_path = f"{user.id}/{dataset_id}.csv"
    client = _client(user)
    await client.upload(storage_path, content)

    try:
        result = await client.rest(
            "POST",
            "datasets",
            body={
                "id": str(dataset_id),
                "user_id": user.id,
                "name": _safe_dataset_name(file.filename),
                "storage_path": storage_path,
                "row_count": row_count,
            },
            prefer="return=representation",
        )
        rows = _rows(result, operation="dataset creation")
        if not rows:
            raise HTTPException(
                status_code=502,
                detail="Supabase did not confirm dataset creation.",
            )
    except HTTPException:
        try:
            await client.delete(storage_path)
        except HTTPException:
            logger.exception("Could not clean up an uploaded file after metadata failure.")
        raise

    return rows[0]


@app.get("/api/datasets/{dataset_id}")
async def get_dataset(
    dataset_id: UUID,
    user: CurrentUser,
):
    client = _client(user)
    dataset = await _owned_dataset(client, user, dataset_id)
    content = await client.download(str(dataset["storage_path"]))
    tab = await run_in_threadpool(
        _read_csv,
        content,
        str(dataset["name"]),
        50,
    )
    columns = []
    for index, header in enumerate(tab.headers):
        values = [row[index] for row in tab.rows if index < len(row)]
        is_number = all(
            str(value).replace(".", "", 1).isdigit()
            for value in values
            if str(value).strip()
        )
        columns.append({
            "name": header,
            "type": "Number" if is_number else "Text",
            "unique": len({str(value) for value in values}),
        })

    return {
        "id": str(dataset["id"]),
        "name": dataset["name"],
        "row_count": int(dataset["row_count"]),
        "columns": columns,
        "rows": tab.rows,
    }


@app.get("/api/conversations")
async def list_conversations(
    user: CurrentUser,
    dataset_id: UUID | None = None,
):
    client = _client(user)
    params = {
        "select": "id,dataset_id,title,created_at,updated_at",
        "user_id": f"eq.{user.id}",
        "order": "updated_at.desc",
    }
    if dataset_id is not None:
        await _owned_dataset(client, user, dataset_id)
        params["dataset_id"] = f"eq.{dataset_id}"
    rows = _rows(
        await client.rest("GET", "conversations", params=params),
        operation="conversation list",
    )
    return {"conversations": rows}


@app.post("/api/conversations")
async def create_conversation(
    request: ConversationCreate,
    user: CurrentUser,
):
    client = _client(user)
    await _owned_dataset(client, user, request.dataset_id)
    rows = _rows(
        await client.rest(
            "POST",
            "conversations",
            body={
                "user_id": user.id,
                "dataset_id": str(request.dataset_id),
                "title": request.title,
            },
            prefer="return=representation",
        ),
        operation="conversation creation",
    )
    if not rows:
        raise HTTPException(
            status_code=502,
            detail="Supabase did not confirm conversation creation.",
        )
    return rows[0]


@app.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: UUID,
    user: CurrentUser,
):
    client = _client(user)
    await _owned_conversation(client, user, conversation_id)
    return {"messages": await _get_messages(client, user, conversation_id)}


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    user: CurrentUser,
):
    client = _client(user)
    conversation = await _owned_conversation(
        client,
        user,
        request.conversation_id,
    )
    if str(conversation.get("dataset_id")) != str(request.dataset_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    dataset = await _owned_dataset(client, user, request.dataset_id)
    previous_messages = await _get_messages(client, user, request.conversation_id)
    history = [
        Turn(role=row["role"], text=row["content"])
        for row in previous_messages[-10:]
        if row.get("role") in ("user", "assistant")
        and isinstance(row.get("content"), str)
    ]

    content = await client.download(str(dataset["storage_path"]))
    name = str(dataset["name"])
    with tempfile.TemporaryDirectory(prefix="toolkit-agent-") as directory:
        csv_path = Path(directory) / f"{name}.csv"
        csv_path.write_bytes(content)
        adapter = CsvFolderAdapter(directory)
        with using_sheet_adapter(adapter):
            result = await run_agent(
                request.message,
                source="api",
                history=history,
                persist_history=False,
            )

        updated_content = csv_path.read_bytes()
        if updated_content != content:
            await client.upload(
                str(dataset["storage_path"]),
                updated_content,
                upsert=True,
            )
            await client.rest(
                "PATCH",
                "datasets",
                params={
                    "id": f"eq.{request.dataset_id}",
                    "user_id": f"eq.{user.id}",
                },
                body={"row_count": _csv_row_count(updated_content)},
                prefer="return=minimal",
            )

    tool_used = result.trail[0].get("tool") if result.trail else None
    tool_used = str(tool_used) if tool_used is not None else None
    answer = result.answer or result.why or "I could not complete that request."
    created_at = datetime.now(UTC)
    await client.rest(
        "POST",
        "messages",
        body=[
            {
                "user_id": user.id,
                "conversation_id": str(request.conversation_id),
                "role": "user",
                "content": request.message,
                "tool_used": None,
                "created_at": created_at.isoformat(),
            },
            {
                "user_id": user.id,
                "conversation_id": str(request.conversation_id),
                "role": "assistant",
                "content": answer,
                "tool_used": tool_used,
                "created_at": (created_at + timedelta(microseconds=1)).isoformat(),
            },
        ],
        prefer="return=minimal",
    )
    await client.rest(
        "PATCH",
        "conversations",
        params={
            "id": f"eq.{request.conversation_id}",
            "user_id": f"eq.{user.id}",
        },
        body={
            "updated_at": (created_at + timedelta(microseconds=1)).isoformat(),
            **({"title": request.message[:120]} if not previous_messages else {}),
        },
        prefer="return=minimal",
    )
    return ChatResponse(
        answer=answer,
        tool_used=tool_used,
        conversation_id=request.conversation_id,
    )

# api/main.py
import re
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, BinaryIO

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from toolkit.adapters.registry import reset, sheet
from toolkit.brain.agent import run_agent_sync
from toolkit.config import settings


def activate_existing_uploads() -> None:
    upload_dir = settings().data_dir / "uploads"
    if any(upload_dir.glob("*.csv")):
        settings().csv_path = upload_dir
        reset()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    activate_existing_uploads()
    yield


app = FastAPI(lifespan=lifespan)

# Allow the React app to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    answer: str
    tool_used: str | None = None


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    result = run_agent_sync(req.message)
    tool_used = None
    if result.trail and len(result.trail) > 0:
        tool_used = result.trail[0].get("tool")
    return ChatResponse(
        answer=result.answer,
        tool_used=tool_used
    )


@app.post("/api/upload")
async def upload_file(file: Annotated[UploadFile, File()]):
    if not file.filename or Path(file.filename.replace("\\", "/")).suffix.lower() != ".csv":
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    filename = Path(file.filename.replace("\\", "/")).name
    tab_name = re.sub(r"[^A-Za-z0-9 _.-]", "_", Path(filename).stem)
    tab_name = re.sub(r"^[^A-Za-z0-9]+", "", tab_name).strip(" .")[:100]
    if not tab_name:
        tab_name = "dataset"

    upload_dir = settings().data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{tab_name}.csv"
    await run_in_threadpool(_write_uploaded_file, file.file, file_path)

    settings().csv_path = upload_dir
    reset()
    return {"filename": file_path.name, "dataset": tab_name, "status": "success"}


@app.get("/api/dataset")
async def get_dataset(dataset: str | None = None):
    adapter = sheet()
    tabs = adapter.list_tabs()
    if not tabs:
        raise HTTPException(
            status_code=404,
            detail="No dataset loaded. Please upload a CSV.",
        )

    tab_name = dataset or tabs[0]
    if tab_name not in tabs:
        raise HTTPException(status_code=404, detail=f"No dataset called {tab_name!r}.")

    try:
        tab = adapter.read_tab(tab_name, sample=50)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    columns = []
    for i, header in enumerate(tab.headers):
        vals = [row[i] for row in tab.rows if i < len(row)]
        is_num = all(
            str(v).replace(".", "", 1).isdigit()
            for v in vals
            if str(v).strip() != ""
        )
        col_type = "Number" if is_num else "Text"
        columns.append({
            "name": header,
            "type": col_type,
            "unique": len({str(v) for v in vals})
        })

    return {
        "name": tab_name,
        "row_count": tab.row_count,
        "columns": columns,
        "rows": tab.rows
    }


def _write_uploaded_file(source: BinaryIO, destination: Path) -> None:
    with destination.open("wb") as target:
        shutil.copyfileobj(source, target)

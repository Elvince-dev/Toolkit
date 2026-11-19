# api/main.py
import os
import shutil
from pathlib import Path
from fastapi import UploadFile, File, HTTPException
from toolkit.adapters.registry import reset
import toolkit.adapters.registry as reg
from toolkit.config import settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from toolkit.brain.agent import run_agent_sync

app = FastAPI()

# Allow the React app (port 3000) to talk to this API (port 8000)
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
    # Call your existing Python brain
    result = run_agent_sync(req.message)
    
    # Extract the tool name if a direct matcher or agent used one
    tool_used = None
    if result.trail and len(result.trail) > 0:
        tool_used = result.trail[0].get("tool")
        
    return ChatResponse(
        answer=result.answer,
        tool_used=tool_used
    )

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    # 1. Ensure the uploads directory exists
    upload_dir = settings().data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. Save the file
    file_path = upload_dir / file.filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # 3. Point the CSV adapter to this new uploads folder
    # We override the setting for the current session
    new_settings = settings().model_copy(update={"csv_path": upload_dir})
    
    # Clear the lru_cache on settings and adapters so they pick up the new path
    from toolkit.config import settings as settings_func
    settings_func.cache_clear()
    
    # Monkeypatch the new setting into memory for this run
    # (In a real multi-tenant app, you'd pass this per-request, 
    # but for local dev, overriding the global settings is easiest).
    os.environ["TOOLKIT_CSV_PATH"] = str(upload_dir)
    
    # Clear the adapter cache so it reads the new folder
    reset()
    
    return {"filename": file.filename, "status": "success"}
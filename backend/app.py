from __future__ import annotations
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from rich.console import Console

console = Console()

from . import DATA_DIR
from . import load_schedule_data, list_projects
from . import SessionStore
from . import route_query
from . import render_with_llm


# Load once at startup
DATA = load_schedule_data(DATA_DIR)
SESSIONS = SessionStore()

SYSTEM_PROMPT = (Path(__file__).resolve().parent.parent / "prompts" / "system_prompt_schedule.md").read_text(encoding="utf-8")

app = FastAPI(title="CriticalPath AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev-friendly; lock down in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CreateSessionReq(BaseModel):
    proj_id: str

class ChatReq(BaseModel):
    session_id: str
    message: str

@app.get("/api/projects")
def api_projects():
    return {"projects": list_projects(DATA)}

@app.post("/api/session")
def api_session(req: CreateSessionReq):
    s = SESSIONS.create(req.proj_id)
    return {"session_id": s.id, "proj_id": s.proj_id}

@app.post("/api/chat")
def api_chat(req: ChatReq):
    s = SESSIONS.get(req.session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Unknown session_id. Create a session first.")
    user_msg = req.message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="Empty message.")
    # Route + compute
    tool_result = route_query(DATA, s.proj_id, user_msg)

    # Persist history (so users can return to earlier topics)
    SESSIONS.append(s.id, "user", user_msg)

    assistant_text = render_with_llm(SYSTEM_PROMPT, s.history, user_msg, tool_result)
    # console.print("assistant:", assistant_text)
    SESSIONS.append(s.id, "assistant", assistant_text)

    return {"reply": assistant_text, "data": tool_result}

# Serve frontend (simple single-page app)
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

import azure.functions as func
import json 
import traceback
from pathlib import Path
from ..shared.data_loader import load_schedule_data
from ..shared.config import DATA_DIR
from ..shared.session_store import SESSIONS
from ..shared.router import route_query
from ..shared.llm import render_with_llm

SESSION = SESSIONS

def _load_data():
    try:
        return load_schedule_data(DATA_DIR)
    except Exception as e:
        print(f"ERROR loading data: {e}")
        return None

def _load_prompt():
    try:
        return (Path(__file__).parent.parent / "prompts" / "system_prompt_schedule.md").read_text()
    except Exception as e:
        print(f"ERROR loading prompt: {e}")
        return "You are a helpful assistant."

def main(req: func.HttpRequest)-> func.HttpResponse:
    """POST /api/chat - Send a message and get AI analysis."""
    try:
        body = req.get_json()
        session_id = body.get("session_id")
        message = body.get("message", "").strip()

        session = SESSION.get(session_id)
        if not session:
            return func.HttpResponse(
                json.dumps({"error": "Unknown session_id"}),
                status_code=404,
                mimetype="application/json"
            )
        if not message:
            return func.HttpResponse(
                json.dumps({"error":"Empty message"}),
                status_code=400,
                mimetype="application/json"
            )
        
        data = _load_data()
        if not data:
            return func.HttpResponse(
                json.dumps({"error": "Failed to load schedule data"}),
                status_code=500,
                mimetype="application/json"
            )
        
        tool_result = route_query(data, session.proj_id, message)
        SESSION.append(session_id, "user", message)
        
        system_prompt = _load_prompt()
        reply = render_with_llm(system_prompt, session.history, message, tool_result)
        SESSION.append(session_id, "assistant", reply)

        return func.HttpResponse(
            json.dumps({"reply": reply, "data": tool_result}),
            mimetype="application/json"
        )
    except Exception as e:
        error_details = {
            "error": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc()
        }
        print(f"ERROR in /api/chat: {error_details}")
        return func.HttpResponse(
            json.dumps(error_details),
            status_code=500,
            mimetype="application/json"
        )
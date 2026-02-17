import azure.functions as func
import json 
from pathlib import Path
from ..shared.data_loader import load_schedule_data
from ..shared.config import DATA_DIR
from ..shared.session_store import SESSIONS
from ..shared.router import route_query
from ..shared.llm import render_with_llm

DATA = load_schedule_data(DATA_DIR)
SESSION = SESSIONS
SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "system_prompt_schedule.md").read_text()

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
                mimetype="applicaton/json"
            )
        if not message:
            return func.HttpResponse(
                json.dumps({"error":"Empty message"}),
                status_code=400,
                mimetype="application/json"
            )
        
        tool_result = route_query(DATA, session.proj_id, message)
        SESSION.append(session_id, "user", message)
        reply = render_with_llm(SYSTEM_PROMPT, session.history, message, tool_result)
        SESSION.append(session_id, "assistant", reply)

        return func.HttpResponse(
            json.dumps({"reply": reply, "data": tool_result}),
            mimetype="application/json"
        )
    except Exception as e:
         return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
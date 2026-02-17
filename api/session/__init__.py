import azure.functions as func
import json
from ..shared.session_store import SESSIONS

# Note: In serveless, this resets between cold starts.
# For production, use Azure Table Storage or Redis instead.

SESSION = SESSIONS


def main(req: func.HttpRequest) -> func.HttpResponse:
    """POST /api/session - Create a new analysis session."""
    try:
        body = req.get_json()
        proj_id = body.get("proj_id")
        if not proj_id:
            return func.HttpResponse(
                json.dumps({"error": "proj_id required"}),
                status_code=400,
                mimetype="application/json"
            )
        session = SESSION.create(proj_id)
        return func.HttpResponse(
            json.dumps({"session_id": session.id, "proj_id": session.proj_id}),
            mimetype="application/json"
        )
    except Exception as e:
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
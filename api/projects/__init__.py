import azure.functions as func
import json
import traceback
from ..shared.data_loader import load_schedule_data, list_projects
from ..shared.config import DATA_DIR

def main(req: func.HttpRequest)-> func.HttpResponse:
    """GET /api/projects - List available P6 projects."""

    try:
        data = load_schedule_data(DATA_DIR)
        projects = list_projects(data)
        return func.HttpResponse(
            json.dumps({"projects": projects}),
            mimetype="application/json"
        )
    except Exception as e:
        error_details = {
            "error": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc()
        }
        print(f"ERROR in /api/projects: {error_details}")
        return func.HttpResponse(
            json.dumps(error_details),
            status_code=500,
            mimetype="application/json"
        )
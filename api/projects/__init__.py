import azure.functions as func
import json
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
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
import azure.functions as func
import json
from ..shared.version import VERSION, BUILD_DATE, DESCRIPTION


def main(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"version": VERSION, "build_date": BUILD_DATE, "description": DESCRIPTION}, ensure_ascii=False),
        mimetype="application/json; charset=utf-8"
    )
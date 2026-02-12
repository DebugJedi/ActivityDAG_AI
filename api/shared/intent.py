from __future__ import annotations
import re
from typing import Literal

Intent = Literal[
    "CRITICAL_PATH",
    "FLOAT",
    "DURATION",
    "PREDECESSORS",
    "SUCCESSORS",
    "TASK_LOOKUP",
    "HEALTH",
    "UNKNOWN",
]

_TASK_CODE_RE = re.compile(r"\b[A-Z]{1,6}\d{1,6}\b")  # e.g. A1030, EL12
_TASK_ID_RE = re.compile(r"\b\d{4,}\b")  # numeric task ids are often long

def classify_intent(q: str) -> Intent:
    p = (q or "").lower()

    if "critical path" in p or "driving path" in p:
        return "CRITICAL_PATH"
    if "float" in p or "near critical" in p:
        return "FLOAT"
    if "duration" in p or "how long" in p or "finish date" in p or "start date" in p:
        return "DURATION"
    if "predecessor" in p or "depends on" in p or "blocking" in p:
        return "PREDECESSORS"
    if "successor" in p or "what comes after" in p or "downstream" in p:
        return "SUCCESSORS"
    if _TASK_CODE_RE.search(q) or _TASK_ID_RE.search(q):
        # if they mention an activity explicitly, treat as lookup
        if "task" in p or "activity" in p or "what is" in p:
            return "TASK_LOOKUP"
    if "health" in p or "risk" in p or "top" in p or "summary" in p:
        return "HEALTH"

    return "UNKNOWN"

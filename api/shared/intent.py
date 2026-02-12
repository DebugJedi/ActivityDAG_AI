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
    """
    Deterministic intent classifier for schedule questions.
    """
    raw = q or ""
    p = raw.lower()

    has_task_ref = bool(_TASK_CODE_RE.search(raw) or _TASK_ID_RE.search(raw))

    if "critical path" in p or "driving path" in p:
        return "CRITICAL_PATH"
    if "float" in p or "near critical" in p:
        if has_task_ref and any(k in p for k in ["task", "activity", "this", "its", "for"]):
            return "TASK_LOOKUP"
        return "FLOAT"
    if "predecessor" in p or "depends on" in p or "blocking" in p:
        
        return "PREDECESSORS"
    
    if "successor" in p or "what comes after" in p or "downstream" in p:
        return "SUCCESSORS"
    if "duration" in p or "how long" in p or "finish date" in p or "start date" in p:
        if has_task_ref:
            return "TASK_LOOKUP"
        return "DURATION"
    
    if has_task_ref:
        return "TASK_LOOKUP"
    if "health" in p or "risk" in p or "top" in p or "summary" in p:
        return "HEALTH"

    return "UNKNOWN"

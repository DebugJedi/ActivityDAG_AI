from __future__ import annotations
import re
from typing import Literal, Optional, List, Tuple, Dict, Any
from dataclasses import dataclass, field



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

# “Top N”
_TOP_N_RE = re.compile(r"\btop\s+(\d{1,3})\b", re.IGNORECASE)

# Month detection (for “between March and April”, “since last month”, etc.)
_MONTH_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
    re.IGNORECASE,
)

# Near-critical thresholds like “within 5 days”, “under 16 hours”
_WITHIN_DAYS_RE = re.compile(r"\b(within|under|less than)\s+(\d+(?:\.\d+)?)\s*(day|days)\b", re.IGNORECASE)
_WITHIN_HOURS_RE = re.compile(r"\b(within|under|less than)\s+(\d+(?:\.\d+)?)\s*(hr|hrs|hour|hours)\b", re.IGNORECASE)

ProjectMarkers = ("project", "overall", "entire", "schedule", "job", "program")
CompareMarkers = (
    "changed", "change", "difference", "diff", "compare", "between", "since",
    "month over month", "mo m", "mom", "baseline", "last month", "previous update",
)

@dataclass
class QueryFrame:
    text: str
    intent: str
    task_token: Optional[str] = None
    months: List[str] = field(default_factory=list)
    compare_pair: Optional[Tuple[str, str]]=None
    wants_baseline_compare: bool=False
    top_n: Optional[int]=None
    threshold_hours: Optional[float]=None
    confidence: float=0.0
    meta:Dict[str, Any]=field(default_factory=dict)

def extract_task_token(text: str)->Optional[str]:
    if not text:
        return None
    m=_TASK_CODE_RE.search(text.upper())
    if m:
        return m.group(0)
    m = _TASK_ID_RE.search(text)
    if m:
        return m.group(0)
    return None

def extract_top_n(text: str)->Optional[int]:
    if not text:
        return None
    m = _TOP_N_RE.search(text)
    if not m:
        return None
    try:
        n = int(m.group(1))
        return max(1, min(n,200))
    except Exception:
        return None

def extract_months(text: str) -> List[str]:
    if not text:
        return []
    ms = [m.group(1).lower() for m in _MONTH_RE.finditer(text)]
    # normalize to 3-letter abbreviations for consistency
    norm = {
        "january": "jan", "jan": "jan",
        "february": "feb", "feb": "feb",
        "march": "mar", "mar": "mar",
        "april": "apr", "apr": "apr",
        "may": "may",
        "june": "jun", "jun": "jun",
        "july": "jul", "jul": "jul",
        "august": "aug", "aug": "aug",
        "september": "sep", "sept": "sep", "sep": "sep",
        "october": "oct", "oct": "oct",
        "november": "nov", "nov": "nov",
        "december": "dec", "dec": "dec",
    }
    out = []
    for x in ms:
        out.append(norm.get(x, x[:3]))
    # keep order but de-dup
    seen = set()
    uniq = []
    for m in out:
        if m not in seen:
            uniq.append(m)
            seen.add(m)
    return uniq


def extract_threshold_hours(text: str) -> Optional[float]:
    if not text:
        return None
    m = _WITHIN_DAYS_RE.search(text)
    if m:
        try:
            days = float(m.group(2))
            return max(0.0, days * 8.0)  # assumption: 8h/day
        except Exception:
            return None
    m = _WITHIN_HOURS_RE.search(text)
    if m:
        try:
            hrs = float(m.group(2))
            return max(0.0, hrs)
        except Exception:
            return None
    return None


def classify_intent(text: str) -> Tuple[str, float]:
    """
    Returns (intent, confidence).
    Keep this deterministic + fast for Azure Functions.
    """
    raw = text or ""
    p = raw.lower()
    task_ref = bool(_TASK_CODE_RE.search(raw) or _TASK_ID_RE.search(raw))

    # Highly explicit
    if "critical path" in p or "driving path" in p:
        return "CRITICAL_PATH", 0.95

    # Comparisons / changes
    if any(k in p for k in CompareMarkers):
        # Slippage-specific
        if any(k in p for k in ("slip", "slipped", "delayed", "delay", "pushed", "moved")):
            return "SLIPPAGE", 0.85
        return "CHANGE_SUMMARY", 0.75

    # Float
    if "float" in p or "near critical" in p:
        # project-level total float
        if "total float" in p and any(m in p for m in ProjectMarkers):
            return "PROJECT_TOTAL_FLOAT", 0.9
        # task float / lookup is handled by task_ref downstream
        return "FLOAT", 0.8

    # Logic neighborhood
    if any(k in p for k in ("predecessor", "depends on", "blocking")):
        return "PREDECESSORS", 0.85
    if any(k in p for k in ("successor", "what comes after", "downstream")):
        return "SUCCESSORS", 0.85

    # Duration / dates
    if any(k in p for k in ("duration", "how long", "finish date", "start date")):
        return ("TASK_LOOKUP", 0.75) if task_ref else ("DURATION", 0.75)

    # Resources
    if any(k in p for k in ("overallocated", "overallocation", "over allocated", "resource overload")):
        return "RESOURCE_OVERALLOCATED", 0.75

    # Health / risks
    if any(k in p for k in ("health", "risk", "top risks", "compliance", "best practices", "open ends", "dangling")):
        return "HEALTH", 0.7

    # Generic task lookup
    if task_ref:
        return "TASK_LOOKUP", 0.6

    return "UNKNOWN", 0.2


def parse_query(text: str) -> QueryFrame:
    intent, conf = classify_intent(text)
    q = QueryFrame(
        text=text or "",
        intent=intent,
        confidence=conf,
        task_token=extract_task_token(text or ""),
        top_n=extract_top_n(text or ""),
        months=extract_months(text or ""),
        threshold_hours=extract_threshold_hours(text or ""),
        wants_baseline_compare=("baseline" in (text or "").lower()),
    )

    # If two months are mentioned, treat as explicit compare pair
    if len(q.months) >= 2:
        q.compare_pair = (q.months[0], q.months[1])

    # Light extra metadata
    q.meta["has_task_ref"] = bool(q.task_token)
    q.meta["has_compare_terms"] = any(k in (text or "").lower() for k in CompareMarkers)

    return q
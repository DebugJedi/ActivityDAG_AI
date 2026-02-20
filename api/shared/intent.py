from __future__ import annotations

"""
intent.py — Query understanding layer for CriticalPath AI.

  Stage 1 — Regex pre-screen:
    Count ALL intent signals first. If exactly one signal → classify.
    If more than one signal → compound query → bail to LLM immediately.
    This is the core fix: the old code never counted signals, it just returned on first match.

  Stage 2 — LLM classifier (GPT-4o, temperature=0):
    Handles compound queries and ambiguous queries.
    Returns primary intent + secondary_intents list so nothing is dropped.

  Date window extraction (always runs, pure Python, no LLM):
    "next 3 months" → DateWindow(start=today, end=today+90days)
    "in April 2024" → DateWindow(start=2024-04-01, end=2024-04-30)
    "between March and June" → DateWindow(start=2026-03-01, end=2026-06-30)
    "next month" → DateWindow(start=today, end=today+30days)
"""


import re
import json
import os
from datetime import datetime, timedelta, date
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass, field
from dotenv import load_dotenv
load_dotenv()

# Intent vocabulary

VALID_INTENTS = {
    "LIST_ACTIVITIES",      # "show me all activities", "list all tasks"
    "CRITICAL_PATH",        # "what is the critical path", "driving path"
    "FLOAT",                # "top float risks", "near critical tasks"
    "DATE_WINDOW",          # "next 3 months", "starting in April", "between X and Y"
    "DURATION",             # "how long is the project", "total project duration"
    "TASK_LOOKUP",          # "tell me about CON2000", "details on PER1000"
    "PREDECESSORS",         # "what comes before CON2000"
    "SUCCESSORS",           # "what comes after PER1000"
    "HEALTH",               # "schedule health", "open ends", "compliance"
    "PROJECT_TOTAL_FLOAT",  # "what is the project total float"
    "CHANGE_SUMMARY",       # "what changed since last month", "compare to baseline"
    "SLIPPAGE",             # "delayed tasks", "what has slipped"
    "UNKNOWN",              # fallback — agent handles with full context
    'PHASE_FLOAT',          # "float for the construction phase", "risks in procurement"
    'HIGH_FLOAT',          # "tasks with high float", "most flexible activities"
}

# DateWindow — always stores resolved Python date objects, never strings

@dataclass
class DateWindow:
    """
    A resolved date range.

    The key point: by the time this object is created, "next 3 months"
    has already been converted to actual start/end dates using today.
    The rest of the system never needs to do relative date math.
    """
    start:       Optional[date]
    end:         Optional[date]
    description: str  = ""     # human label e.g. "next 3 months"
    is_relative: bool = False  # True when derived from "next N months" etc.

    def is_valid(self) -> bool:
        return self.start is not None or self.end is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start":       str(self.start) if self.start else None,
            "end":         str(self.end)   if self.end   else None,
            "description": self.description,
            "is_relative": self.is_relative,
        }

# QueryFrame — structured output, everything the router needs

@dataclass
class QueryFrame:
    """
    intent:               Primary intent — what the user mainly wants.
    secondary_intents:    Other intents also detected (empty for simple queries).
                          e.g. "critical path and float" →
                          intent=CRITICAL_PATH, secondary_intents=["FLOAT"]
    date_window:          Resolved date range if a time period was mentioned.
    task_token:           Task code or ID if a specific task was named.
    confidence:           0.0–1.0. Router uses agent when below 0.80.
    classification_method: "regex" (fast path) or "llm" (compound/ambiguous).
    """
    text:                   str
    intent:                 str
    secondary_intents:      List[str]           = field(default_factory=list)
    task_token:             Optional[str]       = None
    date_window:            Optional[DateWindow] = None
    top_n:                  Optional[int]       = None
    threshold_hours:        Optional[float]     = None
    wants_baseline_compare: bool                = False
    confidence:             float               = 0.0
    classification_method:  str                = "regex"
    meta:                   Dict[str, Any]      = field(default_factory=dict)

# Regex patterns

_TASK_CODE_RE = re.compile(r"\b[A-Z]{1,6}\d{1,6}\b")       # CON2000, PER1000
_TASK_ID_RE   = re.compile(r"\b\d{4,}\b")                   # 141166
_TOP_N_RE     = re.compile(r"\btop\s+(\d{1,3})\b", re.IGNORECASE)

# Relative date expressions
_WITHIN_MONTHS_RE = re.compile(r"\bnext\s+(\d+(?:\.\d+)?)\s*months?\b",  re.IGNORECASE)
_WITHIN_WEEKS_RE  = re.compile(r"\bnext\s+(\d+(?:\.\d+)?)\s*weeks?\b",   re.IGNORECASE)
_WITHIN_DAYS_RE   = re.compile(r"\bnext\s+(\d+(?:\.\d+)?)\s*days?\b",    re.IGNORECASE)
_NEXT_MONTH_RE    = re.compile(r"\bnext\s+month\b",                       re.IGNORECASE)  # "next month" (no number)

# Float threshold expressions: "within 5 days", "under 16 hours"
_THRESHOLD_DAYS_RE  = re.compile(r"\b(within|under|less than)\s+(\d+(?:\.\d+)?)\s*(day|days)\b",           re.IGNORECASE)
_THRESHOLD_HOURS_RE = re.compile(r"\b(within|under|less than)\s+(\d+(?:\.\d+)?)\s*(hr|hrs|hour|hours)\b",  re.IGNORECASE)

# Month names: "April", "Apr", "april 2024"
_MONTH_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\b")  # 03/15/2024
_YEAR_RE = re.compile(r"\b(20\d{2})\b")

_COMPARE_MARKERS = (
    "changed","change","difference","diff","compare","since",
    "baseline","last month","previous update","mom","month over month",
)

_MONTH_MAP = {
    "jan":1,"january":1,"feb":2,"february":2,"mar":3,"march":3,
    "apr":4,"april":4,"may":5,"jun":6,"june":6,"jul":7,"july":7,
    "aug":8,"august":8,"sep":9,"sept":9,"september":9,
    "oct":10,"october":10,"nov":11,"november":11,"dec":12,"december":12,
}

_PHASE_KEYWORDS = (
    "design", "construction", "permit", "civil", "electrical",
    "procurement", "environmental", "closeout", "scoping", "commissioning"
)

_PHASE_MAP = {
    "design":          "design",
    "construction":    "construction",
    "permit":          "permit",
    "civil":           "civil",
    "electrical":      "electrical",
    "procurement":     "procurement",
    "environmental":   "environmental",
    "closeout":        "closeout",
    "scoping":         "scoping",
    "commissioning":   "commissioning",
}
# Date window extraction — pure Python, no LLM

def _last_day_of_month(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _resolve_month_year(month_str: str, year_str: Optional[str], today: date) -> Optional[date]:
    mn = _MONTH_MAP.get(month_str.lower())
    if not mn:
        return None
    if year_str:
        try:
            return date(int(year_str), mn, 1)
        except Exception:
            return None
    # No year given: use current year, next year if month already passed
    candidate = date(today.year, mn, 1)
    if candidate < today:
        candidate = date(today.year + 1, mn, 1)
    return candidate


def _parse_date_match(m: re.Match) -> Optional[date]:
    try:
        a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if c < 100:
            c += 2000
        return date(c, a, b)
    except Exception:
        return None


def extract_date_window(text: str, today: date) -> Optional[DateWindow]:
    """
    Extract and RESOLVE a date window from natural language.

    Priority order:
      1. "next N months/weeks/days" → relative to today
      2. "next month"               → today to today+30 days
      3. Explicit dates MM/DD/YYYY
      4. Month range "between March and June 2026"
      5. Single month "in April 2024"
      6. "this year" / "next year"

    Returns None if no date expression found.
    """
    p = text.lower()

    # 1a. "next N months"
    m = _WITHIN_MONTHS_RE.search(p)
    if m:
        n = float(m.group(1))
        return DateWindow(
            start=today, end=today + timedelta(days=round(n * 30)),
            description=f"next {m.group(1)} months", is_relative=True,
        )

    # 1b. "next N weeks"
    m = _WITHIN_WEEKS_RE.search(p)
    if m:
        n = float(m.group(1))
        return DateWindow(
            start=today, end=today + timedelta(weeks=n),
            description=f"next {m.group(1)} weeks", is_relative=True,
        )

    # 1c. "next N days"
    m = _WITHIN_DAYS_RE.search(p)
    if m:
        n = float(m.group(1))
        return DateWindow(
            start=today, end=today + timedelta(days=n),
            description=f"next {m.group(1)} days", is_relative=True,
        )

    # 1d. "next month" (no number)
    if _NEXT_MONTH_RE.search(p):
        return DateWindow(
            start=today, end=today + timedelta(days=30),
            description="next month", is_relative=True,
        )

    # 2. Explicit dates MM/DD/YYYY
    date_matches = list(_DATE_RE.finditer(text))
    if len(date_matches) >= 2:
        d1 = _parse_date_match(date_matches[0])
        d2 = _parse_date_match(date_matches[1])
        if d1 and d2:
            s, e = (d1, d2) if d1 <= d2 else (d2, d1)
            return DateWindow(start=s, end=e, description=f"{s} to {e}", is_relative=False)
    elif len(date_matches) == 1:
        d1 = _parse_date_match(date_matches[0])
        if d1:
            return DateWindow(start=d1, end=d1, description=str(d1), is_relative=False)

    # 3. Month range or single month
    month_matches = list(_MONTH_RE.finditer(text))
    if len(month_matches) >= 2:
        yr = _YEAR_RE.findall(text)
        yr1 = yr[0] if yr else None
        yr2 = yr[1] if len(yr) > 1 else yr1
        d1 = _resolve_month_year(month_matches[0].group(1), month_matches[0].group(2) or yr1, today)
        d2 = _resolve_month_year(month_matches[-1].group(1), month_matches[-1].group(2) or yr2, today)
        if d1 and d2:
            s, e = (d1, d2) if d1 <= d2 else (d2, d1)
            return DateWindow(
                start=s, end=_last_day_of_month(e),
                description=f"{month_matches[0].group(1)} to {month_matches[-1].group(1)}",
                is_relative=False,
            )
    elif len(month_matches) == 1:
        yr = _YEAR_RE.findall(text)
        d1 = _resolve_month_year(
            month_matches[0].group(1), month_matches[0].group(2) or (yr[0] if yr else None), today
        )
        if d1:
            return DateWindow(
                start=d1, end=_last_day_of_month(d1),
                description=f"{month_matches[0].group(1)} {d1.year}",
                is_relative=False,
            )

    # 4. "this year" / "next year"
    if "this year" in p:
        return DateWindow(
            start=date(today.year, 1, 1), end=date(today.year, 12, 31),
            description=f"this year ({today.year})", is_relative=True,
        )
    if "next year" in p:
        return DateWindow(
            start=date(today.year + 1, 1, 1), end=date(today.year + 1, 12, 31),
            description=f"next year ({today.year + 1})", is_relative=True,
        )

    return None

# Other extractors

def extract_task_token(text: str) -> Optional[str]:
    if not text:
        return None
    m = _TASK_CODE_RE.search(text.upper())
    if m:
        return m.group(0)
    m = _TASK_ID_RE.search(text)
    return m.group(0) if m else None


def extract_top_n(text: str) -> Optional[int]:
    if not text:
        return None
    m = _TOP_N_RE.search(text)
    if not m:
        return None
    try:
        return max(1, min(int(m.group(1)), 200))
    except Exception:
        return None


def extract_threshold_hours(text: str) -> Optional[float]:
    """Extract float threshold: 'within 5 days' → 40.0 hrs, 'under 16 hours' → 16.0 hrs."""
    if not text:
        return None
    m = _THRESHOLD_DAYS_RE.search(text)
    if m:
        try:
            return max(0.0, float(m.group(2)) * 8.0)
        except Exception:
            return None
    m = _THRESHOLD_HOURS_RE.search(text)
    if m:
        try:
            return max(0.0, float(m.group(2)))
        except Exception:
            return None
    return None

def _extract_phase(text: str) -> Optional[str]:
    p = text.lower()
    for keyword, canonical in _PHASE_MAP.items():
        if keyword in p:
            return canonical
    return None

# Stage 1: Signal detection — counts ALL intent signals before classifying



def _detect_signals(p: str, task_ref: bool) -> Dict[str, bool]:
    """
    Detect which intent signals are present in the query.

    Called FIRST in _regex_classify so we can count signals before deciding
    anything. If count > 1, the query is compound and goes to the LLM.

    Note on total_float vs float:
      "total float" is more specific than "float" — when total_float matches,
      the float signal is suppressed so they don't both count as active.
      This prevents "what is the project total float" from looking compound.
    """
    has_date = bool(
        _WITHIN_MONTHS_RE.search(p) or _WITHIN_WEEKS_RE.search(p) or
        _WITHIN_DAYS_RE.search(p)   or _NEXT_MONTH_RE.search(p)   or
        _MONTH_RE.search(p)         or "this year" in p or "next year" in p
    )

    total_float_hit = "total float" in p and not task_ref

    phase_float_hit = (
        ("float" in p or "risk" in p or "at risk" in p or "near critical" in p or "near-critical" in p) and
        any(k in p for k in _PHASE_KEYWORDS) and
        not total_float_hit
    )

    high_float_hit = (
        any(k in p for k in (
            "slip without", "safely delay", "delay if", "reallocate",
            "high float", "most float", "buffer", "flexibility"
        )) and
        not total_float_hit and
        not phase_float_hit
    )

    return {
        "list":          bool(re.search(r"\b(list|show|display|give me|all)\b.{0,30}\b(activit|task|work)", p)),
        "critical_path": "critical path" in p or "driving path" in p or ("driving" in p and "finish" in p),
        # Suppress float when more specific signals match
        "float":         ("float" in p or "near critical" in p or "near-critical" in p) and not total_float_hit and not phase_float_hit and not high_float_hit,
        "total_float":   total_float_hit,
        "phase_float":   phase_float_hit,
        "high_float":    high_float_hit,
        "date":          has_date,
        "predecessor":   any(k in p for k in ("predecessor", "depends on", "blocking", "what comes before")),
        "successor":     any(k in p for k in ("successor", "what comes after", "downstream")),
        "task_lookup":   task_ref and any(k in p for k in (
                             "duration", "how long", "finish", "start",
                             "when", "details", "tell me about",
                         )),
        "duration":      not task_ref and not ("driving" in p) and any(k in p for k in (
            "how long", "total duration", "duration of the project", "how many days", "length of the schedule",
            "project duration", "when does", "project finish", "project start",
        )),
        "compare":       any(k in p for k in _COMPARE_MARKERS),
        "health":        any(k in p for k in ("health", "open end", "dangling", "compliance", "best practice")),
    }

# Stage 1: Regex pre-screen

def _regex_classify(text: str) -> Tuple[Optional[str], float]:
    """
    count signals first → if >1 → return (None, 0.0) → LLM handles it

    Returns:
      (intent, confidence) for single clear intent
      (None, 0.0) for compound, ambiguous, or unmatched queries
    """
    p        = text.lower()
    task_ref = bool(_TASK_CODE_RE.search(text) or _TASK_ID_RE.search(text))

    signals      = _detect_signals(p, task_ref)
    active_count = sum(signals.values())

    # COMPOUND → always defer to LLM (it returns secondary_intents)
    if active_count > 1:
        return None, 0.0

    # Single signal → safe to classify with regex
    if signals["list"]: return "LIST_ACTIVITIES", 0.92
    if signals["critical_path"]: return "CRITICAL_PATH", 0.95
    if signals["total_float"]: return "PROJECT_TOTAL_FLOAT", 0.90
    if signals["float"]: return "FLOAT", 0.85
    if signals["phase_float"]: return "PHASE_FLOAT", 0.88
    if signals["high_float"]: return "HIGH_FLOAT", 0.85
    if signals["date"]: return "DATE_WINDOW", 0.88
    if signals["predecessor"] and task_ref: return "PREDECESSORS", 0.88
    if signals["successor"] and task_ref: return "SUCCESSORS", 0.88
    if signals["task_lookup"]: return "TASK_LOOKUP", 0.80
    if signals["duration"]: return "DURATION", 0.80
    if signals["compare"]:
        if any(k in p for k in ("slip", "slipped", "delayed", "delay", "pushed", "moved")):
            return "SLIPPAGE", 0.85
        return "CHANGE_SUMMARY", 0.75
    if signals["health"]: return "HEALTH", 0.75
    return None, 0.0


# Stage 2

_CLASSIFIER_SYSTEM_PROMPT = """You are a Primavera P6 schedule assistant query classifier.

Analyze the user's question and return a JSON object with exactly these fields:
  - "intent": the PRIMARY intent (one value from the list below)
  - "secondary_intents": list of ALL OTHER intents also present (can be [])
  - "confidence": float between 0.0 and 1.0
  - "reasoning": one sentence explaining why

Intent values (ONLY these are valid):
  LIST_ACTIVITIES     — user wants to see all or many activities
  CRITICAL_PATH — critical path, driving path, which tasks drive the finish date, driving activities
  FLOAT               — float values, near-critical tasks, float risk, schedule buffer
  DATE_WINDOW         — activities in a specific time period
  DURATION            — project duration, how long something takes
  TASK_LOOKUP         — details about one specific named task
  PREDECESSORS        — what comes before a specific task
  SUCCESSORS          — what comes after a specific task
  HEALTH              — overall schedule health, risks, open ends
  PROJECT_TOTAL_FLOAT — project-level total float (not task-level)
  CHANGE_SUMMARY      — what changed between schedule updates
  SLIPPAGE            — delayed or slipped tasks
  UNKNOWN             — cannot determine
  PHASE_FLOAT  — float risk for a specific WBS phase or task type (design, construction, permits)
  HIGH_FLOAT   — tasks with high float, safely delayable tasks, reallocation opportunities

CRITICAL RULE: secondary_intents must list ALL other intents present in the query.
Example: "what is the critical path and which tasks have low float?"
→ {"intent":"CRITICAL_PATH","secondary_intents":["FLOAT"],"confidence":0.92,"reasoning":"..."}

Respond with ONLY valid JSON. No markdown, no text outside the JSON object.
"""


def _llm_classify(text: str) -> Tuple[str, float, List[str]]:
    """
    Use llm to classify compound/ambiguous queries.
    Returns (intent, confidence, secondary_intents).
    Falls back to UNKNOWN on any error — never crashes the request.
    """
    try:
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key = os.getenv("AZURE_OPENAI_API_KEY"),
            api_version = "2024-02-01",
            azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT"),
        )
        resp = client.chat.completions.create(
            model    = "gpt-4o",
            messages = [
                {"role": "system", "content": _CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": f"Classify this query: {text}"},
            ],
            max_tokens  = 150,
            temperature = 0,   # fully deterministic
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$",          "", raw)

        parsed = json.loads(raw)
        intent = parsed.get("intent", "UNKNOWN")
        if intent not in VALID_INTENTS:
            intent = "UNKNOWN"
        confidence = float(parsed.get("confidence", 0.5))
        secondary  = [i for i in parsed.get("secondary_intents", []) if i in VALID_INTENTS]
        return intent, confidence, secondary

    except Exception as e:
        print(f"[intent] LLM classifier failed: {type(e).__name__}: {e}")
        return "UNKNOWN", 0.2, []

# Main entry point


def parse_query(text: str, today: Optional[date] = None) -> QueryFrame:
    """
    Parse a raw user query into a structured QueryFrame.

    Always call with today=date.today() from your API endpoint.
    This is what makes "next 3 months" resolve to actual calendar dates.

    Args:
        text:  Raw user query string
        today: Reference date. Always pass date.today() explicitly from the API layer.
    """
    today = today or date.today()
    text  = text  or ""

    # Always extract these — they don't depend on intent classification
    task_token  = extract_task_token(text)
    phase_filter = _extract_phase(text)
    top_n = extract_top_n(text)
    date_window = extract_date_window(text, today)
    threshold = extract_threshold_hours(text)

    # Stage 1: fast regex pre-screen
    regex_intent, regex_conf = _regex_classify(text)

    if regex_intent is not None and regex_conf >= 0.80:
        # Single intent, high confidence — skip LLM entirely
        return QueryFrame(
            text = text,
            intent = regex_intent,
            secondary_intents = [],      # regex never detects compound intents
            task_token = task_token,
            date_window = date_window,
            top_n = top_n,
            threshold_hours = threshold,
            wants_baseline_compare = "baseline" in text.lower(),
            confidence = regex_conf,
            classification_method = "regex",
            meta = {
                "has_task_ref":    bool(task_token),
                "has_date_window": date_window is not None,
                "today":           str(today),
                "phase_filter":    phase_filter or "",
            },
        )

    # Stage 2: LLM for compound/ambiguous queries
    llm_intent, llm_conf, secondary = _llm_classify(text)

    # If date window was extracted but LLM didn't pick DATE_WINDOW as primary,
    # promote DATE_WINDOW to primary — the router must gather windowed data first.
    # e.g. "near critical tasks starting next month"
    #   LLM → intent=FLOAT, but we have a date window
    #   Promote → intent=DATE_WINDOW, secondary_intents=["FLOAT"]
    final_secondary = secondary
    final_intent = llm_intent

    if date_window and date_window.is_valid() and llm_intent != "DATE_WINDOW":
        final_secondary = [llm_intent] + [i for i in secondary if i != llm_intent]
        final_intent    = "DATE_WINDOW"

    return QueryFrame(
        text = text,
        intent = final_intent,
        secondary_intents = final_secondary,
        task_token = task_token,
        date_window = date_window,
        top_n = top_n,
        threshold_hours = threshold,
        wants_baseline_compare = "baseline" in text.lower(),
        confidence = llm_conf,
        classification_method = "llm",
        meta = {
            "has_task_ref": bool(task_token),
            "has_date_window": date_window is not None,
            "today": str(today),
            "regex_intent": regex_intent,
            "regex_conf": regex_conf,
        },
    )
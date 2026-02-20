from __future__ import annotations

"""
analytics.py - Data gathering layer for CriticalPath AI.

Philosophy:
  These functions GATHER data. They do NOT summarize, filter aggressively,
  or make judgments about what is "important". That is the LLM's job.

  Key rules:
    - Never cap results at an arbitrary number without the caller asking.
    - Always include BOTH critical (float=0) AND near-critical tasks in
      float risk queries - they are different things.
    - Date window filtering uses resolved Python date objects (from intent.py),
      never strings, never relative math done here.
    - Return rich context so the LLM can reason, not pre-digested conclusions.
"""

from typing import Dict, List, Any, Optional, Callable
import pandas as pd
import networkx as nx
from .schedule_graph import longest_time_path, _to_float
import math
from dataclasses import dataclass
from datetime import date, datetime


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_to_numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _safe_to_datetime(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


def _task_cols(df: pd.DataFrame, desired: List[str]) -> List[str]:
    return [c for c in desired if c in df.columns]


def _core_task_fields(df: pd.DataFrame) -> List[str]:
    """Standard set of columns to include in any task result."""
    return _task_cols(df, [
        "task_id", "task_code", "task_name", "wbs_name", "task_type",
        "status_code", "total_float_hr_cnt", "target_drtn_hr_cnt",
        "target_start_date", "target_end_date",
        "early_start_date", "early_end_date",
        "late_start_date", "late_end_date",
        "act_start_date", "act_end_date",
        "phys_complete_pct",
    ])


def _float_days(hr_val) -> Optional[float]:
    try:
        v = float(hr_val)
        if math.isnan(v):
            return None
        return round(v / 8.0, 2)
    except Exception:
        return None

def _clean_records(records: list) -> list:
    """Replace NaN/inf values with None so the result is JSON-serializable."""
    cleaned = []
    for row in records:
        clean_row = {}
        for k, v in row.items():
            try:
                if v is None:
                    clean_row[k] = None
                elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    clean_row[k] = None
                else:
                    clean_row[k] = v
            except Exception:
                clean_row[k] = None
        cleaned.append(clean_row)
    return cleaned
    
# ---------------------------------------------------------------------------
# ToolSpec - kept for heuristic_candidates compatibility
# ---------------------------------------------------------------------------

@dataclass
class ToolSpec:
    name: str
    description: str
    run: Callable[..., Any]
    trigger_keywords: tuple = ()
    priority: int = 0


def heuristic_candidates(query: str, tools: list) -> list:
    q = query.lower()
    scored = []
    for t in tools:
        score = sum(1 for kw in t.trigger_keywords if kw in q)
        if score:
            scored.append((score, t.priority, t))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, _, t in scored[:5]]


# ---------------------------------------------------------------------------
# 1. List all activities
# ---------------------------------------------------------------------------

def list_all_activities(tasks: pd.DataFrame) -> Dict[str, Any]:
    """
    Return every activity in the project with full scheduling context.
    No caps, no filtering - the LLM can reason about the full set.
    """
    if tasks.empty:
        return {"activities": [], "count": 0, "note": "No activities found for this project."}

    df = tasks.copy()
    df["_tf"]  = _safe_to_numeric(df.get("total_float_hr_cnt", pd.Series(dtype=float)))
    df["float_days"] = df["_tf"].apply(lambda x: round(x / 8.0, 2) if pd.notna(x) else None)

    cols = _core_task_fields(df) + ["float_days"]
    cols = list(dict.fromkeys(cols))  # deduplicate, preserve order

    records =  _clean_records(df[_task_cols(df, cols)].to_dict(orient="records"))
    return {
        "activities": records,
        "count": len(records),
        "summary": {
            "total": len(df),
            "not_started": int((df.get("status_code","") == "TK_NotStart").sum()),
            "in_progress": int((df.get("status_code","") == "TK_Active").sum()),
            "complete":    int((df.get("status_code","") == "TK_Complete").sum()),
        },
    }


# ---------------------------------------------------------------------------
# 2. Activities in a date window
# ---------------------------------------------------------------------------

def activities_in_window(
    tasks: pd.DataFrame,
    window_start: Optional[date],
    window_end: Optional[date],
    date_field: str = "both",   # "start", "end", or "both" (either starts OR ends in window)
) -> Dict[str, Any]:
    """
    Return activities whose early_start_date or early_end_date falls within
    the given window. Also flags activities that SPAN the window (in progress
    during the window even if they don't start/end within it).

    date_field:
      "start" - activity starts within window
      "end"   - activity finishes within window
      "both"  - either starts OR finishes within window (default)
    """
    if tasks.empty:
        return {"activities": [], "count": 0, "window": {}, "note": "No activities."}

    df = tasks.copy()
    df["_es"] = _safe_to_datetime(df.get("early_start_date", pd.Series(dtype=str)))
    df["_ef"] = _safe_to_datetime(df.get("early_end_date",   pd.Series(dtype=str)))

    # Convert window boundaries to pandas Timestamps for comparison
    ts_start = pd.Timestamp(window_start) if window_start else None
    ts_end   = pd.Timestamp(window_end)   if window_end   else None

    def _in_window(ts: pd.Series) -> pd.Series:
        mask = pd.Series([True] * len(df), index=df.index)
        if ts_start:
            mask = mask & (ts >= ts_start)
        if ts_end:
            mask = mask & (ts <= ts_end)
        return mask

    if date_field == "start":
        mask = _in_window(df["_es"])
    elif date_field == "end":
        mask = _in_window(df["_ef"])
    else:
        # "both": starts OR ends in window
        mask = _in_window(df["_es"]) | _in_window(df["_ef"])

    # Also find activities that SPAN the window (started before, ending after)
    span_mask = pd.Series([False] * len(df), index=df.index)
    if ts_start and ts_end:
        span_mask = (df["_es"] < ts_start) & (df["_ef"] > ts_end)

    windowed = df[mask].copy()
    spanning = df[span_mask & ~mask].copy()

    # Add float days column
    for frame in [windowed, spanning]:
        if "total_float_hr_cnt" in frame.columns:
            frame["float_days"] = _safe_to_numeric(frame["total_float_hr_cnt"]).apply(
                lambda x: round(x / 8.0, 2) if pd.notna(x) else None
            )

    cols = _core_task_fields(df) + ["float_days"]
    cols = list(dict.fromkeys(cols))

    return {
        "window": {
            "start": str(window_start) if window_start else None,
            "end":   str(window_end)   if window_end   else None,
        },
        "activities_starting_or_finishing":  _clean_records(windowed[_task_cols(windowed, cols)].to_dict(orient="records")),
        "activities_spanning_window": _clean_records(spanning[_task_cols(spanning, cols)].to_dict(orient="records")),
        "counts": {
            "starting_or_finishing": len(windowed),
            "spanning": len(spanning),
        },
        "note": (
            f"'starting_or_finishing' = activities whose early start or early end falls within the window. "
            f"'spanning' = activities already underway throughout the entire window."
        ),
    }


# ---------------------------------------------------------------------------
# 3. Float risk analysis - FIXED
# ---------------------------------------------------------------------------

def float_risk_analysis(
    tasks: pd.DataFrame,
    near_critical_threshold_days: float = 30.0,
    top_n: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Complete float risk picture:
      - Critical tasks (float = 0)
      - Near-critical tasks (0 < float <= threshold)
      - Non-critical tasks sorted by float ascending (lowest buffer first)

    KEY FIX: Critical and near-critical are returned SEPARATELY.
    The old top_float_risks() lumped them together and hit the 15-cap
    before near-critical tasks could surface.

    near_critical_threshold_days: tasks with float <= this many days are "near critical".
    top_n: if set, caps the non-critical list for LLM context size reasons.
    """
    if "total_float_hr_cnt" not in tasks.columns:
        return {"note": "No total_float_hr_cnt column found.", "critical": [], "near_critical": [], "non_critical": []}

    df = tasks.copy()
    df["_tf"]        = _safe_to_numeric(df["total_float_hr_cnt"])
    df["float_days"] = df["_tf"].apply(lambda x: round(x / 8.0, 2) if pd.notna(x) else None)
    df = df[df["_tf"].notna()].copy()

    threshold_hr = near_critical_threshold_days * 8.0

    critical     = df[df["_tf"] <= 0].sort_values("_tf", ascending=True)
    near_crit    = df[(df["_tf"] > 0) & (df["_tf"] <= threshold_hr)].sort_values("_tf", ascending=True)
    non_critical = df[df["_tf"] > threshold_hr].sort_values("_tf", ascending=True)

    if top_n:
        non_critical = non_critical.head(top_n)

    cols = _core_task_fields(df) + ["float_days"]
    cols = list(dict.fromkeys(cols))

    def _to_records(frame: pd.DataFrame) -> List[Dict]:
        return _clean_records(frame[_task_cols(frame, cols)].to_dict(orient="records"))

    return {
        "critical": _to_records(critical),
        "near_critical": _to_records(near_crit),
        "non_critical": _to_records(non_critical),
        "counts": {
            "critical": len(critical),
            "near_critical": len(near_crit),
            "non_critical": len(non_critical),
            "total": len(df),
        },
        "threshold": {
            "days": near_critical_threshold_days,
            "hours": threshold_hr,
        },
        "float_stats": {
            "min_days":    round(float(df["_tf"].min()) / 8.0, 2) if not df.empty else None,
            "max_days":    round(float(df["_tf"].max()) / 8.0, 2) if not df.empty else None,
            "median_days": round(float(df["_tf"].median()) / 8.0, 2) if not df.empty else None,
        },
    }

def float_by_phase(
    tasks: pd.DataFrame,
    phase_filter: str,
    near_critical_threshold_days: float = 30.0,
) -> Dict[str, Any]:
    """
    Float risk filtered by WBS phase name or task code prefix.
    Handles: 'which design tasks are at risk', 'construction near-critical',
             'permits with no float'
    """
    if not phase_filter:
        return {"note": "No phase filter provided.", "critical": [], "near_critical": [], "non_critical": []}

    df = tasks.copy()

    # Match against wbs_name OR task_code prefix
    wbs_mask  = df.get("wbs_name", pd.Series(dtype=str)).astype(str).str.contains(
        phase_filter, case=False, na=False
    )
    code_mask = df.get("task_code", pd.Series(dtype=str)).astype(str).str.contains(
        phase_filter.upper(), case=False, na=False
    )
    filtered = df[wbs_mask | code_mask]

    if filtered.empty:
        return {
            "note": f"No tasks found matching phase '{phase_filter}'. "
                    f"Available WBS phases: {sorted(df['wbs_name'].dropna().unique().tolist()) if 'wbs_name' in df.columns else 'unknown'}",
            "phase_filter": phase_filter,
            "critical": [], "near_critical": [], "non_critical": [],
        }

    result = float_risk_analysis(filtered, near_critical_threshold_days=near_critical_threshold_days)
    result["phase_filter"] = phase_filter
    result["matched_task_count"] = len(filtered)
    return result

# ---------------------------------------------------------------------------
# 4. Project total float
# ---------------------------------------------------------------------------

def project_total_float(tasks: pd.DataFrame) -> Dict[str, Any]:
    """
    Best-effort project-level Total Float based on the finish milestone.
    """
    if "total_float_hr_cnt" not in tasks.columns:
        return {"note": "No total_float_hr_cnt column found."}

    df = tasks.copy()
    df["_tf"]  = _safe_to_numeric(df["total_float_hr_cnt"])
    df["_end"] = _safe_to_datetime(df.get("target_end_date", pd.Series(dtype=str)))

    if df["_tf"].notna().sum() == 0:
        return {"note": "total_float_hr_cnt exists but all values are null/unparseable."}

    # Prefer finish milestones
    basis_df     = pd.DataFrame()
    basis_reason = None

    if "task_type" in df.columns:
        cand = df[df["task_type"].astype(str).str.contains("FinMile", case=False, na=False)]
        if not cand.empty:
            basis_df     = cand.copy()
            basis_reason = "task_type contains FinMile"

    if basis_df.empty and "task_name" in df.columns:
        cand = df[df["task_name"].astype(str).str.contains(
            r"project\s*complete|finish\b|substantial\s*complete", case=False, na=False
        )]
        if not cand.empty:
            basis_df     = cand.copy()
            basis_reason = "task_name matched finish keywords"

    if basis_df.empty and df["_end"].notna().any():
        basis_df     = df.loc[[df["_end"].idxmax()]].copy()
        basis_reason = "latest target_end_date"

    if basis_df.empty:
        basis_df     = df[df["_tf"].notna()].head(1).copy()
        basis_reason = "first non-null total float (fallback)"

    if len(basis_df) > 1 and basis_df["_end"].notna().any():
        basis_df = basis_df.loc[[basis_df["_end"].idxmax()]]

    basis    = basis_df.iloc[0].to_dict()
    basis_tf = basis.get("_tf")

    try:
        project_tf = float(basis_tf)
        if math.isnan(project_tf):
            raise ValueError
    except Exception:
        project_tf   = float(df["_tf"].min())
        basis_reason = (basis_reason or "") + " | fallback=min_total_float"

    valid = df[df["_tf"].notna()].copy()
    critical = valid[valid["_tf"] <= 0] 
    near_critical = valid[(valid["_tf"] > 0) & (valid["_tf"] <= 240)] #1-30 days
    low_float = valid[(valid["_tf"] >240) & (valid["_tf"] <= 800)] #30-100 days
    high_float = valid[valid["_tf"] > 800] # >100 days

    most_float_row = valid.loc[valid["_tf"].idxmax()] if not valid.empty else None

    return {
        "project_total_float_hr":       round(project_tf, 3),
        "project_total_float_days":     round(project_tf / 8.0, 2),
        "basis_reason":                 basis_reason,
        "basis_task": {
            "task_code": str(basis.get("task_code", "")),
            "task_name": str(basis.get("task_name", "")),
            "task_type": str(basis.get("task_type", "")),
            "total_float_hr_cnt": str(basis.get("total_float_hr_cnt", "")),
        },
         "intepretation": (
            "A finish milestone float of 0 is normal in CPM - it means the project end date "
            "is the dealine. Individual task may still have significant float. "
            "See float_distribution for full picture."
        ),
        "float_distribution": {
            "critical_0_days":          int(len(critical)),
            "near_critical_1_30_days":  int(len(near_critical)),
            "low_float_30_100_days":    int(len(low_float)),
            "high_float_over_100_days": int(len(high_float)),
            "total_tasks":              int(len(valid)),
        },
        "stats": {
            "min_float_days":    round(float(df["_tf"].min()) / 8.0, 2),
            "max_float_days":    round(float(df["_tf"].max()) / 8.0, 2),
            "median_float_days": round(float(df["_tf"].median()) / 8.0, 2),
        },
       "most_float_task": {
            "task_code":  str(most_float_row.get("task_code", "")),
            "task_name":  str(most_float_row.get("task_name", "")),
            "float_days": round(float(most_float_row["_tf"]) / 8.0, 1),
        },
    }


# ---------------------------------------------------------------------------
# 5. Project duration
# ---------------------------------------------------------------------------

def project_duration(tasks: pd.DataFrame) -> Dict[str, Any]:
    if "target_start_date" in tasks.columns and "target_end_date" in tasks.columns:
        start = _safe_to_datetime(tasks["target_start_date"]).min()
        end   = _safe_to_datetime(tasks["target_end_date"]).max()
        if pd.notna(start) and pd.notna(end):
            return {
                "start":         str(start.date()),
                "finish":        str(end.date()),
                "duration_days": int((end - start).days),
            }

    if "target_drtn_hr_cnt" in tasks.columns:
        dur_hr = _safe_to_numeric(tasks["target_drtn_hr_cnt"]).fillna(0).sum()
        return {
            "duration_hours_sum":    float(dur_hr),
            "duration_days_8h_sum":  round(float(dur_hr) / 8.0, 2),
            "note": "Sum of task durations (not schedule-driven). Dates missing.",
        }

    return {"note": "No duration data available."}


# ---------------------------------------------------------------------------
# 6. Critical path summary (graph-based)
# ---------------------------------------------------------------------------

def critical_path_summary(G: nx.DiGraph) -> Dict[str, Any]:
    if G.number_of_nodes() == 0:
        return {"path": [], "count": 0, "note": "No tasks in project graph."}

    if not nx.is_directed_acyclic_graph(G):
        driving = [
            n for n, d in G.nodes(data=True)
            if str(d.get("driving_path_flag", "")).upper() == "Y"
        ]
        rendered = [
            {
                "task_id":   tid,
                "task_code": G.nodes[tid].get("task_code", ""),
                "task_name": G.nodes[tid].get("task_name", ""),
                "wbs_name":  G.nodes[tid].get("wbs_name", ""),
                "duration_hr": float(_to_float(G.nodes[tid].get("duration_hr", 0.0))),
            }
            for tid in driving[:200]
        ]
        return {
            "path":  rendered,
            "count": len(rendered),
            "note":  "Graph has cycles; returned tasks marked driving_path_flag=Y.",
        }

    path     = longest_time_path(G)
    rendered = [
        {
            "task_id": tid,
            "task_code": G.nodes[tid].get("task_code", ""),
            "task_name": G.nodes[tid].get("task_name", ""),
            "wbs_name": G.nodes[tid].get("wbs_name", ""),
            "duration_hr": float(_to_float(G.nodes[tid].get("duration_hr", 0.0))),
            "total_float_hr_cnt": G.nodes[tid].get("total_float_hr_cnt",
                                                    G.nodes[tid].get("total_float_hr", "")),
        }
        for tid in path[:200]
    ]
    return {"path": rendered, "count": len(path)}


# ---------------------------------------------------------------------------
# 7. Critical and near-critical (kept for backward compat, delegates to new fn)
# ---------------------------------------------------------------------------

def critical_and_near_critical(tasks: pd.DataFrame, threshold_hours: float = 40.0) -> Dict[str, Any]:
    """Backward-compatible wrapper. Delegates to float_risk_analysis."""
    threshold_days = threshold_hours / 8.0
    result = float_risk_analysis(tasks, near_critical_threshold_days=threshold_days)
    return {
        "critical": result["critical"],
        "near_critical": result["near_critical"],
        "counts": result["counts"],
        "threshold_hours": threshold_hours,
    }


# ---------------------------------------------------------------------------
# 8. top_float_risks (kept for backward compat)
# ---------------------------------------------------------------------------

def top_float_risks(tasks: pd.DataFrame, top_n: int = 15) -> Dict[str, Any]:
    """
    FIXED: Now returns critical and near-critical SEPARATELY,
    so the LLM sees both groups clearly even if critical tasks fill
    the list numerically.
    """
    result = float_risk_analysis(tasks, near_critical_threshold_days=60.0, top_n=top_n)
    return {
        "critical_tasks": result["critical"],
        "near_critical_tasks": result["near_critical"],
        "counts": result["counts"],
        "threshold_days": 60.0,
        "note": (
            "Critical = float <= 0 days. "
            "Near-critical = 0 < float <= 60 days. "
            "Both groups drive schedule risk."
        ),
    }
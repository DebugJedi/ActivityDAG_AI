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
import numpy as np
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

def _cost_numeric(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([0.0] * len(df), index=df.index)
    return _safe_to_numeric(df[col]).fillna(0.0)

def _round_cost(v: float)-> float:
    return round(v, 2)

def _join_rsrc(taskrsrc: pd.DataFrame, rsrc: pd.DataFrame) -> pd.DataFrame:
    """Join resource names into taskrsrc"""
    if rsrc is None or rsrc.empty:
        return taskrsrc
    cols = [c for c in ["rsrc_id", "rsrc_name", "rsrc_short_name"] if c in rsrc.columns]

    return taskrsrc.merge(rsrc[cols], on="rsrc_id", how="left")

def _join_wbs(tasks: pd.DataFrame, wbs: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Join WBS name into tasks if not already present."""
    if wbs is None or wbs.empty or "wbs_name" in tasks.columns:
        return tasks
    if "wbs_id" not in tasks.columns or "wbs_id" not in wbs.columns:
        return tasks
    w = wbs[["wbs_id", "wbs_name"]].drop_duplicates()
    return tasks.merge(w, on="wbs_id", how="left") 

def _float_days(hr_val) -> Optional[float]:
    try:
        v = float(hr_val)
        if math.isnan(v):
            return None
        return round(v / 8.0, 2)
    except Exception:
        return None

def _clean_records(records: list) -> list:
    cleaned = []
    for row in records:
        clean_row = {}
        for k, v in row.items():
            try:
                if v is None:
                    clean_row[k] = None
                elif isinstance(v, set):               # ← ADD THIS
                    clean_row[k] = sorted(list(v))     # set → sorted list
                elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    clean_row[k] = None
                elif isinstance(v, (int, float)) and pd.isna(v):
                    clean_row[k] = None
                elif hasattr(v, 'item'):
                    clean_row[k] = v.item()
                elif str(type(v)) == "<class 'pandas._libs.missing.NAType'>":
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



# Slippage

def slippage_analysis(
        tasks: pd.DataFrame,
        threshold_days: float = 0.0,
) -> Dict[str, Any]:
    """
    Comopare baseline (target) vs current forecast (early)
    A task is slippage when early_date > target_date.
    
    threshold_days: minimum slip to include (0=any slip, 5 => 5days slip)
    Returns:
        slipped_tasks tasks behind baseline
        ahead_tasks: tasks ahead of baseline
        on_baseline: tasks with no variance
        summary: counts and worst slippage
    """
    if tasks.empty:
        return {"slipped_tasks": [], "ahead_tasks": [], "on_baseline": [],
                "summary": {}, "note": "No tasks found."}
    
    df = tasks.copy()
    df["_te"] = _safe_to_datetime(df.get("target_end_date", pd.Series(dtype=str)))
    df["_ee"] = _safe_to_datetime(df.get("early_end_date", pd.Series(dtype=str)))
    df["_ts"] = _safe_to_datetime(df.get("target_start_date", pd.Series(dtype=str)))
    df["_es"] = _safe_to_datetime(df.get("early_start_date", pd.Series(dtype=str)))

    df["finish_variance_days"] = (df["_ee"] - df["_te"]).dt.days
    df["start_variance_days"] = (df["_es"] - df["_ts"]).dt.days

    df["finish_variance_days"] = df["finish_variance_days"].where(
        df["finish_variance_days"].notna(), other= None
    )
    df["start_variance_days"] = df["start_variance_days"].where(
        df["start_variance_days"].notna(), other=None
    )
    df = df[df["finish_variance_days"].notna()].copy()

    slipped = df[df["finish_variance_days"] > threshold_days].sort_values(
        "finish_variance_days", ascending=False
    )
    ahead = df[df["finish_variance_days"] < -threshold_days].sort_values(
        "finish_variance_days", ascending= True
    )
    on_baseline = df[df["finish_variance_days"].abs() <= threshold_days]

    base_cols = _core_task_fields(df)
    extra_cols = ["finish_variance_days", "start_variance_days"]
    cols = list(dict.fromkeys(base_cols + extra_cols))

    def _rec(frame: pd.DataFrame) -> List[Dict]:
        return _clean_records(frame[_task_cols(frame, cols)].to_dict(orient="records"))

    worst = slipped.iloc[0] if not slipped.empty else None

    return {
        "slipped_tasks": _rec(slipped),
        "ahead_tasks": _rec(ahead),
        "on_baseline": _rec(on_baseline),
        "summary": {
            "total_tasks": len(df),
            "slipped_count": len(slipped),
            "ahead_count": len(ahead),
            "on_baseline_count": len(on_baseline),
            "worst_slip_days": int(slipped["finish_variance_days"].max()) if not slipped.empty else 0,
            "worst_slip_task": worst["taks_code"] if worst is not None else None, 
            "worst_slip_name": worst["task_name"] if worst is not None else None,
            "avg_slip_days": round(float(slipped["finish_variance_days"].mean()), 1) if not slipped.empty else 0,
            "threshold_days": threshold_days,
        },
        "note": (
            "finish_variance_days > 0 means task is BEHIND baseline. "
            "finish_variance_days < 0 means task is AHEAD of baseline. "
            "Baseline  = target_end_date, Forecast = early_end_date." 
        ),
    }

def project_end_date_variance(
    tasks: pd.DataFrame,
    projects: Optional[pd.DataFrame] = None,
    proj_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare project-level baseline finish vs current forecast finish. """

    result: Dict[str, Any] = {}

    if projects is not None and proj_id is not None and "proj_id" in projects.columns:
        projects = projects[projects["proj_id"].astype(str) == str(proj_id)]

    if "early_end_date" in tasks.columns:
        ee = _safe_to_datetime(tasks["early_end_date"])
        forecast_finish = ee.max()
        result["forecast_finish"] = str(forecast_finish.date()) if pd.notna(forecast_finish) else None
    else:
        result["forecast_finish"] = None

    if "target_end_date" in tasks.columns:
        te = _safe_to_datetime(tasks["target_end_date"])
        baseline_finish = te.max()
        result["baseline_finish"] = str(baseline_finish.date()) if pd.notna(baseline_finish) else None

    else:
        result["baseline_finish"] = None

    if projects is not None and "scd_end_date" in projects.columns:
        scd = _safe_to_datetime(projects["scd_end_date"])
        result["scheduled_completion_date"] = str(scd.max().date()) if pd.notna(scd.max()) else None
    else:
        result["scheduled_completion_date"] = None
    
    if result["forecast_finish"] and result["baseline_finish"]:
        f = pd.Timestamp(result["forecast_finish"])
        b = pd.Timestamp(result["baseline_finish"])
        variance = (f -b).days
        result["variance_days"] = variance
        result["variance_direction"] = (
            "BEHIND baseline" if variance > 0
            else "AHEAD of baseline" if variance < 0
            else "ON baseline"
        )
    else:
        result["variance_days"] = None
        result["variance_direction"] = "Cannot compute - missing dates"
    
    result["note"] = (
        "baseline_finish = max target_end_date across all tasks."
        "forecast_finish = max early_end_date (current CPM forecast)."
        "scheduled_completion_date = scd_end_date from PROJECT table (contractual deadline)."
    )

    return result

# Budget / Cost analysis

def total_budget(
        taskrsrc: pd.DataFrame,
        rsrc: Optional[pd.DataFrame] =None,
) -> Dict[str, Any]:
    """
    Project toatl budget brokeen down by resource type.
    Uses target_cost from TASKRSRC as budget figure.
    """
    if taskrsrc is None or taskrsrc.empty:
        return {"note": "No resource assignment data (TASKRSRC) available."}
    
    df = taskrsrc.copy()
    df["target_cost"] = _cost_numeric(df, "target_cost")
    df["act_reg_cost"] = _cost_numeric(df, "act_reg_cost")
    df["remain_cost"] = _cost_numeric(df, "remain_cost")

    total = df["target_cost"].sum()
    actual = df["act_reg_cost"].sum()
    remain = df["remain_cost"].sum()

    by_type = (
        df.groupby("rsrc_type")[["target_cost", "act_reg_cost", "remain_cost"]]
        .sum()
        .round(2)
    )
    type_breakdown = []
    for rtype, row in by_type.iterrows():
        type_breakdown.append({
            "resource_type": rtype,
            "label": {"RT_Labor": "Labor", "RT_Equip": "Equipment", "RT_Mat": "Material"}.get(rtype, rtype),
            "budget": _round_cost(row["target_cost"]),
            "actual_cost": _round_cost(row["act_reg_cost"]),
            "remaining_cost": _round_cost(row["remain_cost"]),
            "budget_pct": round(row["target_cost"] / total * 100, 1) if total else 0,
        })

    return {
        "total_budget": _round_cost(total),
        "total_actual_cost": _round_cost(actual),
        "total_remaining": _round_cost(remain),
        "percent_spend": round(actual / total * 100, 1) if total else 0,
        "by_resource_type": type_breakdown,
        "currency": "USD",
        "note": "budget = target_cost. actual = act_reg_cost. remaining = remain_cost.",
    }

def budget_by_phase(
        tasks: pd.DataFrame,
        taskrsrc: pd.DataFrame,
        wbs: Optional[pd.DataFrame] = None,
        phase_filter: Optional[str] =None,
) -> Dict[str, Any]:
    """
    Budget breakdown by WBS phase.
    Joins TAKSRSRC -> TASK -> WBS to group costs by schedule phase.
    phase_filter: Optional substring to filter to a specific phase.
    """

    if taskrsrc is None or taskrsrc.empty:
        return {"note": "No resource assingment data (TASKRSRC) available."}
    
    tasks_with_wbs = _join_wbs(tasks.copy(), wbs)

    df = taskrsrc.copy()
    df["target_cost"] = _cost_numeric(df, "target_cost")
    df["act_reg_cost"] = _cost_numeric(df, "act_reg_cost")
    df["remain_cost"] = _cost_numeric(df, "remain_cost")

    task_cols_needed = [c for c in ["task_id", "task_code", "task_name", "wbs_id", "wbs_name"] if c in tasks_with_wbs.columns]
    merged = df.merge(tasks_with_wbs[task_cols_needed], on="task_id", how="left")

    if "wbs_name" not in merged.columns:
        return {"note": "WBS datea not available - cannot break down by phase."}
    
    if phase_filter:
        mask = merged["wbs_name"].astype(str).str.contains(phase_filter, case=False, na=False)
        merged = merged[mask]
        if merged.empty:
            return {
                "note": f"No cost data found for phase '{phase_filter}'.",
                "phase_filter": phase_filter,
                "phases": [],
            }
        
    by_phase = (
        merged.groupby("wbs_name")[["target_cost", "act_reg_cost", "remain_cost"]]
        .sum()
        .sort_values("target_cost", ascending=False)
        .round(2)
    )

    total = by_phase["target_cost"].sum()
    phases = []
    for wbs_name, row in by_phase.iterrows():
        phases.append({
            "phase": wbs_name,
            "budget": _round_cost(row["target_cost"]),
            "actual_cost": _round_cost(row["act_reg_cost"]),
            "remaining_cost": _round_cost(row["remain_cost"]),
            "budget_pct": round(row["target_cost"] / total * 100, 1) if total else 0,
        })

    return {
        "phases": phases,
        "total_budget": _round_cost(total),
        "phase_count": len(phases),
        "phase_filter": phase_filter,
    }

def top_activities_by_cost(
        tasks: pd.DataFrame,
        taskrsrc: pd.DataFrame,
        wbs: Optional[pd.DataFrame] = None,
        top_n: int = 20,
        rsrc_type_filter: Optional[str] = None,
) -> Dict[str, Any]:
    if taskrsrc is None or taskrsrc.empty:
        return {"note": "No resource assignment data (TASKRSRC) available."}

    df = taskrsrc.copy()
    df["target_cost"] = _cost_numeric(df, "target_cost")

    if rsrc_type_filter:
        df = df[df["rsrc_type"].astype(str) == rsrc_type_filter]

    tasks_with_wbs = _join_wbs(tasks.copy(), wbs)
    task_cols_needed = [c for c in ["task_id", "task_code", "task_name", "wbs_name",
                                    "early_start_date", "early_end_date", "status_code"]
                        if c in tasks_with_wbs.columns]

    merged = df.merge(tasks_with_wbs[task_cols_needed], on="task_id", how="left")

    groupby_cols = list([c for c in ["task_id", "task_code", "task_name", "wbs_name"]
                         if c in merged.columns])

    by_task = (
        merged.groupby(groupby_cols, as_index=False)["target_cost"]
        .sum()
        .sort_values("target_cost", ascending=False)
        .head(top_n)
    )

    activities = []
    for _, row in by_task.iterrows():
        activities.append({
            "task_code": str(row.get("task_code", "")),
            "task_name": str(row.get("task_name", "")),
            "wbs_phase": str(row.get("wbs_name", "")),
            "budget": _round_cost(float(row["target_cost"])),
        })

    return {
        "activities": activities,
        "count": len(activities),
        "top_n": top_n,
        "total_budget": _round_cost(float(by_task["target_cost"].sum())),
        "rsrc_type_filter": str(rsrc_type_filter) if rsrc_type_filter else None,
    }

def resource_cost_breakdown(
        taskrsrc: pd.DataFrame,
        rsrc: Optional[pd.DataFrame] = None,
        top_n: int = 20,
        rsrc_type_filter: Optional[str] = None,
) -> Dict[str, Any]:
    
    if taskrsrc is None or taskrsrc.empty:
        return {"note": "No resource assignment data (TASKRSRC) available."}
    
    df = _join_rsrc(taskrsrc.copy(), rsrc)
    df["target_cost"] = _cost_numeric(df, "target_cost")
    df["act_reg_cost"] = _cost_numeric(df, "act_reg_cost")
    df["remain_cost"] = _cost_numeric(df, "remain_cost")
    df["target_qty"] = _cost_numeric(df, "target_qty")

    if rsrc_type_filter:
        df = df[df["rsrc_type"].astype(str) == rsrc_type_filter]

    name_col = "rsrc_name" if "rsrc_name" in df.columns else "rsrc_id"

    by_rsrc = (
        df.groupby([name_col, "rsrc_type"])[["target_cost", "act_reg_cost", "remain_cost", "target_qty"]]
        .sum()
        .sort_values("target_cost", ascending=False)
        .head(top_n)
        .reset_index()
    )

    resources = []

    for _, row in by_rsrc.iterrows():
        rtype = str(row.get("rsrc_type", ""))
        resources.append({
            "resource_name": str(row.get(name_col, "")),
            "resource_type": rtype,
            "type_label": {"RT_Labor": "Labor", "RT_Equip": "Equipment", "RT_Mat": "Material"}.get(rtype, rtype),
            "budget": _round_cost(row["target_cost"]),
            "actual_cost": _round_cost(row["act_reg_cost"]),
            "remaining_cost": _round_cost(row["remain_cost"]),
            "planned_hours": _round_cost(row["target_qty"]),
        })

    return {
        "resources":        resources,
        "count":            len(resources),
        "top_n":            top_n,
        "rsrc_type_filter": rsrc_type_filter,
    }

def tasks_for_resource(
    tasks: pd.DataFrame,
    taskrsrc: pd.DataFrame,
    rsrc: Optional[pd.DataFrame] = None,
    resource_name: Optional[str] = None,
    resource_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    All tasks assigned to a specific resource.
    Lookup by resource name (fuzzy) or exact rsrc_id.
    """
    if taskrsrc is None or taskrsrc.empty:
        return {"note": "No resource assignment data available."}

    df = _join_rsrc(taskrsrc.copy(), rsrc)
    df["target_cost"] = _cost_numeric(df, "target_cost")
    df["target_qty"]  = _cost_numeric(df, "target_qty")

    # Find matching resource
    if resource_id:
        mask = df["rsrc_id"].astype(str) == str(resource_id)
    elif resource_name:
        name_col = "rsrc_name" if "rsrc_name" in df.columns else "rsrc_id"
        mask = df[name_col].astype(str).str.contains(resource_name, case=False, na=False)
    else:
        return {"note": "Provide resource_name or resource_id."}

    matched = df[mask]
    if matched.empty:
        available = df["rsrc_name"].dropna().unique().tolist() if "rsrc_name" in df.columns else []
        return {
            "note": f"Resource '{resource_name or resource_id}' not found.",
            "available_resources": sorted(available)[:20],
        }

    # Join task details
    task_cols_needed = [c for c in ["task_id", "task_code", "task_name", "wbs_name",
                                     "early_start_date", "early_end_date",
                                     "status_code", "total_float_hr_cnt"] if c in tasks.columns]
    merged = matched.merge(tasks[task_cols_needed], on="task_id", how="left")

    task_list = []
    for _, row in merged.iterrows():
        task_list.append({
            "task_code":     str(row.get("task_code", "")),
            "task_name":     str(row.get("task_name", "")),
            "wbs_phase":     str(row.get("wbs_name", "")),
            "planned_hours": _round_cost(row.get("target_qty", 0)),
            "budget":        _round_cost(row.get("target_cost", 0)),
            "start_date":    str(row.get("early_start_date", "")),
            "end_date":      str(row.get("early_end_date", "")),
            "status":        str(row.get("status_code", "")),
        })

    rsrc_name = matched["rsrc_name"].iloc[0] if "rsrc_name" in matched.columns else resource_id
    return {
        "resource_name":    str(rsrc_name),
        "resource_type":    str(matched["rsrc_type"].iloc[0]) if "rsrc_type" in matched.columns else "",
        "tasks":            task_list,
        "task_count":       len(task_list),
        "total_budget":     _round_cost(matched["target_cost"].sum()),
        "total_hours":      _round_cost(matched["target_qty"].sum()),
    }


def critical_path_cost(
    tasks: pd.DataFrame,
    taskrsrc: pd.DataFrame,
    critical_task_ids: List[str],
) -> Dict[str, Any]:
    """
    Budget for tasks on the critical path specifically.
    Pass critical_task_ids from critical_path_summary().
    """
    if taskrsrc is None or taskrsrc.empty or not critical_task_ids:
        return {"note": "No critical path or resource data available."}

    df = taskrsrc.copy()
    df["target_cost"] = _cost_numeric(df, "target_cost")
    df["task_id_str"] = df["task_id"].astype(str)

    cp_rsrc = df[df["task_id_str"].isin([str(t) for t in critical_task_ids])]

    total = cp_rsrc["target_cost"].sum()
    by_type = cp_rsrc.groupby("rsrc_type")["target_cost"].sum().round(2).to_dict()

    return {
        "critical_path_budget":  _round_cost(total),
        "critical_task_count":   len(critical_task_ids),
        "by_resource_type":      by_type,
        "note": "Budget for tasks on the critical path only.",
    }


# 1. List all activities


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
         "interpretation": (
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
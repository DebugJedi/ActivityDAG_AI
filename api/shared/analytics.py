from __future__ import annotations
from typing import Dict, List, Any, Optional, Callable
import pandas as pd
import networkx as nx
from .schedule_graph import longest_time_path, _to_float
import math
from dataclasses import dataclass
from pydantic import BaseModel, Field
import re

@dataclass
class ToolSpec:
    name: str
    description: str
    run: Callable[..., Any]
    trigger_keywords: tuple[str, ...]=()
    priority: int =0


def heuristic_candidates(query: str, tools: list[ToolSpec])->list[ToolSpec]:
    q = query.lower()
    scored = []
    for t in tools:
        score = 0
        for kw in t.trigger_keywords:
            if kw in  q:
                score+=1
        
        if score:
            scored.append((score, t.priority, t))
    scored.sort(key=lambda x: x[0], reverse =True )
    return [t for _, t in scored[:5]]




def _safe_to_numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")

def _safe_to_datetime(s: pd.Series)-> pd.Series:
    return pd.to_datetime(s, errors="coerce")

def _task_cols(df:pd.DataFrame, desired: List[str])-> List[str]:
    return [c for c in desired if c in df.columns]

def _render_task_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Keep outputs compact + JSON-serializable."""
    out = {}
    for k in ["task_id", "task_code", "task_name", "wbs_name", "task_type",
              "total_float_hr_cnt", "target_drtn_hr_cnt", "target_start_date", "target_end_date"]:
        if k in row:
            out[k] = row.get(k)
    return out


# -----------------------------
# Analytics
# -----------------------------
def project_total_float(tasks: pd.DataFrame) -> Dict[str, Any]:
    """
    Best-effort project-level Total Float.

    Strategy (in order):
    1) task_type indicates finish milestone (FinMile* etc) -> choose the LATEST finish among them
    2) name-based finish milestone -> choose LATEST finish among matches
    3) latest target_end_date in the project
    4) fallback: first non-null float

    NOTE:
    - In CPM, “project total float” is typically interpreted from the project finish milestone’s float.
    - If your schedule has multiple finish milestones, we choose the one with the latest target_end_date.
    """
    if "total_float_hr_cnt" not in tasks.columns:
        return {"note": "No total_float_hr_cnt column found."}

    df = tasks.copy()

    # Float + End date normalization
    df["_tf"] = _safe_to_numeric(df["total_float_hr_cnt"])
    if "target_end_date" in df.columns:
        df["_end"] = _safe_to_datetime(df["target_end_date"])
    else:
        df["_end"] = pd.NaT

    # If everything is NaN, stop early
    if df["_tf"].notna().sum() == 0:
        return {"note": "total_float_hr_cnt exists but all values are null/unparseable."}

    basis_df = pd.DataFrame()
    basis_reason = None

    # 1) Prefer finish milestone by task_type
    if "task_type" in df.columns:
        cand = df[df["task_type"].astype(str).str.contains("FinMile", case=False, na=False)].copy()
        if not cand.empty:
            basis_df = cand
            basis_reason = "task_type contains FinMile"

    # 2) Name-based finish milestone
    if basis_df.empty and "task_name" in df.columns:
        cand = df[df["task_name"].astype(str).str.contains(
            r"project\s*complete|finish\b|substantial\s*complete",
            case=False,
            na=False
        )].copy()
        if not cand.empty:
            basis_df = cand
            basis_reason = "task_name matched finish keywords"

    # 3) Latest finish date
    if basis_df.empty and df["_end"].notna().any():
        basis_df = df.loc[[df["_end"].idxmax()]].copy()
        basis_reason = "latest target_end_date"

    # 4) Final fallback
    if basis_df.empty:
        basis_df = df[df["_tf"].notna()].head(1).copy()
        basis_reason = "first non-null total float"

    # If multiple candidates, pick the one with the latest end date (if available)
    if len(basis_df) > 1 and basis_df["_end"].notna().any():
        basis_df = basis_df.loc[[basis_df["_end"].idxmax()]]

    basis = basis_df.iloc[0].to_dict()
    basis_tf = basis.get("_tf")

    # Convert basis float safely
    try:
        project_tf = float(basis_tf)
        if math.isnan(project_tf):
            raise ValueError("basis tf is nan")
    except Exception:
        # As a fallback, use the MIN float (most constrained) but label this clearly.
        project_tf = float(df["_tf"].min())
        basis_reason = (basis_reason or "") + " | fallback=min_total_float"

    return {
        "project_total_float_hr": round(project_tf, 3),
        "project_total_float_days_8h": round(project_tf / 8.0, 2),  # assumption: 8h/day
        "assumptions": {"hours_per_day": 8.0},
        "basis_reason": basis_reason,
        "basis": _render_task_row({
            "task_id": str(basis.get("task_id", "")),
            "task_code": str(basis.get("task_code", "")),
            "task_name": str(basis.get("task_name", "")),
            "task_type": str(basis.get("task_type", "")),
            "target_end_date": str(basis.get("target_end_date", "")),
            "total_float_hr_cnt": str(basis.get("total_float_hr_cnt", "")),
        }),
        "min_total_float_hr": round(float(df["_tf"].min()), 3) if df["_tf"].notna().any() else None,
        "median_total_float_hr": round(float(df["_tf"].median()), 3) if df["_tf"].notna().any() else None,
        "max_total_float_hr": round(float(df["_tf"].max()), 3) if df["_tf"].notna().any() else None,
    }


def critical_and_near_critical(tasks: pd.DataFrame, threshold_hours: float = 40.0) -> Dict[str, Any]:
    """
    Critical: total float <= 0
    Near critical: 0 < total float <= threshold_hours
    """
    if "total_float_hr_cnt" not in tasks.columns:
        return {"critical": [], "near_critical": [], "counts": {"critical": 0, "near_critical": 0},
                "note": "No total_float_hr_cnt column found."}

    df = tasks.copy()
    df["_tf"] = _safe_to_numeric(df["total_float_hr_cnt"])

    # Ignore NaN float rows from both groups
    df = df[df["_tf"].notna()].copy()

    critical_df = df[df["_tf"] <= 0].copy()
    near_df = df[(df["_tf"] > 0) & (df["_tf"] <= float(threshold_hours))].copy()

    # Sort: most constrained first
    critical_df = critical_df.sort_values(["_tf"], ascending=True)
    near_df = near_df.sort_values(["_tf"], ascending=True)

    cols = _task_cols(df, [
        "task_id", "task_code", "task_name", "wbs_name",
        "total_float_hr_cnt", "target_drtn_hr_cnt", "target_start_date", "target_end_date"
    ])

    return {
        "critical": critical_df[cols].head(50).to_dict(orient="records"),
        "near_critical": near_df[cols].head(50).to_dict(orient="records"),
        "counts": {"critical": int(len(critical_df)), "near_critical": int(len(near_df))},
        "threshold_hours": float(threshold_hours),
    }


def top_float_risks(tasks: pd.DataFrame, top_n: int = 15) -> Dict[str, Any]:
    """
    Returns tasks with lowest total float (highest risk).
    NaN floats are excluded so we don't surface junk.
    """
    if "total_float_hr_cnt" not in tasks.columns:
        return {"risks": [], "note": "No total_float_hr_cnt column found."}

    df = tasks.copy()
    df["_tf"] = _safe_to_numeric(df["total_float_hr_cnt"])
    df = df[df["_tf"].notna()].copy()

    if df.empty:
        return {"risks": [], "note": "total_float_hr_cnt exists but all values are null/unparseable."}

    df = df.sort_values(["_tf"], ascending=True).head(int(top_n))

    cols = _task_cols(df, [
        "task_id", "task_code", "task_name", "wbs_name",
        "total_float_hr_cnt", "target_drtn_hr_cnt", "target_start_date", "target_end_date"
    ])

    return {"risks": df[cols].to_dict(orient="records")}


def project_duration(tasks: pd.DataFrame) -> Dict[str, Any]:
    """
    Prefer schedule dates. If missing, fall back to sum of durations (warning included).
    """
    if "target_start_date" in tasks.columns and "target_end_date" in tasks.columns:
        start = _safe_to_datetime(tasks["target_start_date"]).min()
        end = _safe_to_datetime(tasks["target_end_date"]).max()
        if pd.notna(start) and pd.notna(end):
            return {
                "start": str(start.date()),
                "finish": str(end.date()),
                "duration_days": int((end - start).days),
            }

    # Fallback: sum of durations (NOT schedule-driven)
    if "target_drtn_hr_cnt" in tasks.columns:
        dur_hr = _safe_to_numeric(tasks["target_drtn_hr_cnt"]).fillna(0).sum()
    else:
        dur_hr = 0.0

    return {
        "duration_hours_sum": float(dur_hr),
        "duration_days_8h_sum": round(float(dur_hr) / 8.0, 2),
        "note": "Used sum of durations (not schedule-driven). Target start/end dates missing or unparseable.",
        "assumptions": {"hours_per_day": 8.0},
    }


def critical_path_summary(G: nx.DiGraph) -> Dict[str, Any]:
    """
    Returns a critical path approximation.

    - If DAG: compute longest_time_path(G) (duration-weighted)
    - If cycles exist: fall back to tasks marked driving_path_flag=Y (if present)
    """
    if G.number_of_nodes() == 0:
        return {"path": [], "count": 0, "note": "No tasks found for this project."}

    if not nx.is_directed_acyclic_graph(G):
        driving = [
            n for n, d in G.nodes(data=True)
            if str(d.get("driving_path_flag", "")).upper() == "Y"
        ]
        note = "Graph has cycles; returned tasks marked driving_path_flag=Y."
        if not driving:
            note = "Graph has cycles; no driving_path_flag=Y found. Fix logic/cycles to compute a longest path."
        rendered = []
        for tid in driving[:200]:
            n = G.nodes[tid]
            rendered.append({
                "task_id": tid,
                "task_code": n.get("task_code", ""),
                "task_name": n.get("task_name", ""),
                "wbs_name": n.get("wbs_name", ""),
                "duration_hr": float(_to_float(n.get("duration_hr", 0.0))),
            })
        return {"path": rendered, "count": len(rendered), "note": note}

    path = longest_time_path(G)

    rendered: List[Dict[str, Any]] = []
    for tid in path[:200]:
        n = G.nodes[tid]
        rendered.append({
            "task_id": tid,
            "task_code": n.get("task_code", ""),
            "task_name": n.get("task_name", ""),
            "wbs_name": n.get("wbs_name", ""),
            "duration_hr": float(_to_float(n.get("duration_hr", 0.0))),
            # include float if graph node has it
            "total_float_hr_cnt": n.get("total_float_hr_cnt", n.get("total_float_hr", "")),
        })

    return {"path": rendered, "count": len(path)}
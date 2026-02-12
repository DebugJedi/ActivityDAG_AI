from __future__ import annotations
from typing import Dict, List, Any
import pandas as pd
import networkx as nx
from .schedule_graph import longest_time_path, _to_float
import math


def project_total_float(tasks: pd.DataFrame) -> Dict[str, Any]:
    """
    Approximate project-level total float using the finish milestone (if present),
    otherwise the task with latest target_end_date.
    """
    if "total_float_hr_cnt" not in tasks.columns:
        return {"note": "No total_float_hr_cnt column found."}

    df = tasks.copy()
    df["_tf"] = pd.to_numeric(df["total_float_hr_cnt"], errors="coerce")
    df["_end"] = pd.to_datetime(df["target_end_date"], errors="coerce") if "target_end_date" in df.columns else pd.NaT

    basis_df = pd.DataFrame()

    # Prefer finish milestone
    if "task_type" in df.columns:
        basis_df = df[df["task_type"].astype(str).str.contains("FinMile", case=False, na=False)]

    # Next: name-based finish
    if basis_df.empty and "task_name" in df.columns:
        basis_df = df[df["task_name"].astype(str).str.contains(
            r"project\s*complete|finish\b|substantial\s*complete", case=False, na=False
        )]

    # Next: latest finish
    if basis_df.empty and df["_end"].notna().any():
        basis_df = df.loc[[df["_end"].idxmax()]]

    # Final fallback
    if basis_df.empty:
        basis_df = df.dropna(subset=["_tf"]).head(1)

    basis = basis_df.iloc[0].to_dict()
    basis_tf = basis.get("_tf")
    project_tf = float(basis_tf) if basis_tf is not None and not math.isnan(float(basis_tf)) else float(df["_tf"].min())

    return {
        "project_total_float_hr": round(project_tf, 3),
        "project_total_float_days_8h": round(project_tf / 8.0, 2),  # assumption: 8h/day
        "basis": {
            "task_id": str(basis.get("task_id", "")),
            "task_code": str(basis.get("task_code", "")),
            "task_name": str(basis.get("task_name", "")),
            "task_type": str(basis.get("task_type", "")),
            "target_end_date": str(basis.get("target_end_date", "")),
            "total_float_hr_cnt": str(basis.get("total_float_hr_cnt", "")),
        },
        "min_total_float_hr": round(float(df["_tf"].min()), 3) if df["_tf"].notna().any() else None,
        "median_total_float_hr": round(float(df["_tf"].median()), 3) if df["_tf"].notna().any() else None,
        "max_total_float_hr": round(float(df["_tf"].max()), 3) if df["_tf"].notna().any() else None,
    }


def critical_and_near_critical(tasks: pd.DataFrame, threshold_hours: float = 40.0) -> Dict[str, Any]:
    if "total_float_hr_cnt" not in tasks.columns:
        return {"critical": [], "near_critical": [], "note": "No total_float_hr_cnt column found."}

    tf = pd.to_numeric(tasks["total_float_hr_cnt"], errors="coerce")
    critical_df = tasks[tf <= 0].copy()
    near_df = tasks[(tf > 0) & (tf <= threshold_hours)].copy()

    cols = [c for c in ["task_id", "task_code", "task_name", "wbs_name", "total_float_hr_cnt", "target_drtn_hr_cnt"] if c in tasks.columns]
    return {
        "critical": critical_df[cols].head(50).to_dict(orient="records"),
        "near_critical": near_df[cols].head(50).to_dict(orient="records"),
        "counts": {"critical": int(len(critical_df)), "near_critical": int(len(near_df))},
    }



def top_float_risks(tasks: pd.DataFrame, top_n: int = 15) -> Dict[str, Any]:
    if "total_float_hr_cnt" not in tasks.columns:
        return {"risks": [], "note": "No total_float_hr_cnt column found."}

    tf = pd.to_numeric(tasks["total_float_hr_cnt"], errors="coerce")
    df = tasks.copy()
    df["_tf"] = tf
    df = df.sort_values(["_tf"], ascending=True).head(top_n)
    cols = [c for c in ["task_id", "task_code", "task_name", "wbs_name", "total_float_hr_cnt", "target_drtn_hr_cnt"] if c in df.columns]
    return {"risks": df[cols].to_dict(orient="records")}



def project_duration(tasks: pd.DataFrame) -> Dict[str, Any]:
    # Prefer planned dates if present; else approximate from sum of durations (not perfect).
    if "target_start_date" in tasks.columns and "target_end_date" in tasks.columns:
        start = pd.to_datetime(tasks["target_start_date"], errors="coerce").min()
        end = pd.to_datetime(tasks["target_end_date"], errors="coerce").max()
        if pd.notna(start) and pd.notna(end):
            return {"start": str(start.date()), "finish": str(end.date()), "duration_days": int((end - start).days)}
    # Fallback
    dur_hr = pd.to_numeric(tasks.get("target_drtn_hr_cnt", pd.Series([])), errors="coerce").fillna(0).sum()
    return {"duration_hours_sum": float(dur_hr), "note": "Used sum of durations (not schedule-driven). Dates missing."}



def critical_path_summary(G: nx.DiGraph) -> Dict[str, Any]:
    # If P6 provides driving_path_flag, you can use that, but we also compute a DAG-based approximation.
    if G.number_of_nodes() == 0:
        return {"path": [], "note": "No tasks found for this project."}

    if not nx.is_directed_acyclic_graph(G):
        # Try a heuristic: tasks with driving_path_flag == Y
        driving = [n for n, d in G.nodes(data=True) if str(d.get("driving_path_flag", "")).upper() == "Y"]
        return {"path": driving[:200], "note": "Graph has cycles; returned tasks marked driving_path_flag=Y."}

    path = longest_time_path(G)
    # Render as compact cards
    rendered = []
    for tid in path[:200]:
        n = G.nodes[tid]
        rendered.append({
            "task_id": tid,
            "task_code": n.get("task_code", ""),
            "task_name": n.get("task_name", ""),
            "wbs_name": n.get("wbs_name", ""),
            "duration_hr": float(n.get("duration_hr", 0.0)),
        })
    return {"path": rendered, "count": len(path)}

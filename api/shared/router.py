from __future__ import annotations

from typing import Dict, Any, Optional
import re

from .intent import parse_query
from .schedule_graph import ScheduleGraph
from .analytics import (
    critical_path_summary,
    critical_and_near_critical,
    top_float_risks,
    project_duration,
    project_total_float,
)

_TASK_ID_RE = re.compile(r"\b\d{4,}\b")
_TASK_CODE_RE = re.compile(r"\b[A-Z]{1,6}\d{1,6}\b")


def _find_task_by_code_or_id(tasks_df, token: str) -> Optional[Dict[str, Any]]:
    token = str(token).strip()

    if "task_id" in tasks_df.columns and token.isdigit():
        m = tasks_df[tasks_df["task_id"].astype(str) == token]
        if len(m) > 0:
            return m.iloc[0].to_dict()

    if "task_code" in tasks_df.columns:
        m = tasks_df[tasks_df["task_code"].astype(str).str.upper() == token.upper()]
        if len(m) > 0:
            return m.iloc[0].to_dict()

    return None


def _project_tasks_with_wbs(data, proj_id: str):
    tasks = data.tasks[data.tasks["proj_id"].astype(str) == str(proj_id)].copy()

    # Join WBS name if available (same logic as ScheduleGraph)
    if data.wbs is not None and "wbs_id" in tasks.columns and "wbs_id" in data.wbs.columns:
        w = data.wbs[["wbs_id", "wbs_name"]].drop_duplicates().copy()
        tasks = tasks.merge(w, on="wbs_id", how="left")

    return tasks


def route_query(data, proj_id: str, message: str) -> Dict[str, Any]:
    qf = parse_query(message)
    intent = qf.intent

    tasks = _project_tasks_with_wbs(data, proj_id)

    # --- Project total float ---
    if intent == "PROJECT_TOTAL_FLOAT":
        counts = critical_and_near_critical(tasks, threshold_hours=qf.threshold_hours or 40.0).get("counts", {})
        return {
            "intent": intent,
            "confidence": qf.confidence,
            "project_id": str(proj_id),
            "project_total_float": project_total_float(tasks),
            "critical_near_counts": counts,
        }

    # --- Duration ---
    if intent == "DURATION":
        return {
            "intent": intent,
            "confidence": qf.confidence,
            "project_id": str(proj_id),
            "project_duration": project_duration(tasks),
        }

    # --- Float (task-level or risk list) ---
    if intent == "FLOAT":
        if qf.task_token:
            t = _find_task_by_code_or_id(tasks, qf.task_token)
            if t and "total_float_hr_cnt" in t:
                return {
                    "intent": "TASK_FLOAT",
                    "confidence": qf.confidence,
                    "project_id": str(proj_id),
                    "task": {
                        "task_id": str(t.get("task_id", "")),
                        "task_code": str(t.get("task_code", "")),
                        "task_name": str(t.get("task_name", "")),
                        "wbs_name": str(t.get("wbs_name", "")),
                    },
                    "total_float_hr_cnt": t.get("total_float_hr_cnt"),
                }

        threshold = qf.threshold_hours or 40.0
        return {
            "intent": intent,
            "confidence": qf.confidence,
            "project_id": str(proj_id),
            "top_float_risks": top_float_risks(tasks, top_n=qf.top_n or 15),
            "critical_near": critical_and_near_critical(tasks, threshold_hours=threshold),
            "project_total_float": project_total_float(tasks),
        }

    # --- Requires dependency graph ---
    needs_graph = intent in ("CRITICAL_PATH", "PREDECESSORS", "SUCCESSORS", "TASK_LOOKUP", "HEALTH")
    build = None
    G = None
    if needs_graph:
        sg = ScheduleGraph(data.tasks, data.taskpred, data.wbs)
        build = sg.build_for_project(proj_id)
        G = build.graph

    # --- Critical path ---
    if intent == "CRITICAL_PATH":
        res = critical_path_summary(G)
        return {"intent": intent, "confidence": qf.confidence, "project_id": str(proj_id), **res}

    # --- Neighborhood lookups ---
    if intent in ("PREDECESSORS", "SUCCESSORS", "TASK_LOOKUP"):
        if not qf.task_token:
            return {
                "intent": intent,
                "confidence": qf.confidence,
                "project_id": str(proj_id),
                "note": "Please mention an activity/task code (e.g., CON2000) or a numeric task_id.",
            }

        t = _find_task_by_code_or_id(tasks, qf.task_token)
        if not t:
            return {"intent": intent, "confidence": qf.confidence, "project_id": str(proj_id), "note": f"Task '{qf.task_token}' not found in this project."}

        node_id = str(t.get("task_id", ""))
        if node_id not in G:
            return {
                "intent": intent,
                "confidence": qf.confidence,
                "project_id": str(proj_id),
                "task": t,
                "note": "Task found in table but not in dependency graph (no edges or missing IDs).",
            }

        if intent == "TASK_LOOKUP":
            preds = [{"task_id": p, "task_code": G.nodes[p].get("task_code", ""), "task_name": G.nodes[p].get("task_name", "")} for p in G.predecessors(node_id)]
            succs = [{"task_id": s, "task_code": G.nodes[s].get("task_code", ""), "task_name": G.nodes[s].get("task_name", "")} for s in G.successors(node_id)]
            return {"intent": intent, "confidence": qf.confidence, "project_id": str(proj_id), "task": t, "predecessors": preds[:50], "successors": succs[:50]}

        if intent == "PREDECESSORS":
            preds = [{"task_id": p, "task_code": G.nodes[p].get("task_code", ""), "task_name": G.nodes[p].get("task_name", "")} for p in G.predecessors(node_id)]
            return {"intent": intent, "confidence": qf.confidence, "project_id": str(proj_id), "task": t, "predecessors": preds[:100]}

        succs = [{"task_id": s, "task_code": G.nodes[s].get("task_code", ""), "task_name": G.nodes[s].get("task_name", "")} for s in G.successors(node_id)]
        return {"intent": intent, "confidence": qf.confidence, "project_id": str(proj_id), "task": t, "successors": succs[:100]}

    # --- Not implemented yet (but now you can route them cleanly) ---
    if intent in ("CHANGE_SUMMARY", "SLIPPAGE", "RESOURCE_OVERALLOCATED"):
        return {
            "intent": intent,
            "confidence": qf.confidence,
            "project_id": str(proj_id),
            "note": (
                f"Parsed this as {intent}. The extraction is ready (months={qf.months}, compare_pair={qf.compare_pair}, baseline={qf.wants_baseline_compare}), "
                "but the underlying analytics tool is not implemented yet."
            ),
        }

    # --- Health / Unknown fallback ---
    graph_meta = {}
    if build is not None and G is not None:
        graph_meta = {
            "tasks": int(G.number_of_nodes()),
            "relationships": int(G.number_of_edges()),
            "has_cycles": bool(build.has_cycles),
        }
    else:
        # cheap fallback
        graph_meta = {
            "tasks": int(len(tasks)),
            "relationships": int(len(data.taskpred[data.taskpred["proj_id"].astype(str) == str(proj_id)])) if hasattr(data, "taskpred") else None,
        }

    return {
        "intent": intent,
        "confidence": qf.confidence,
        "project_id": str(proj_id),
        "project_duration": project_duration(tasks),
        "project_total_float": project_total_float(tasks),
        "critical_near": critical_and_near_critical(tasks, threshold_hours=qf.threshold_hours or 40.0),
        "top_float_risks": top_float_risks(tasks, top_n=qf.top_n or 15),
        "graph": graph_meta,
    }
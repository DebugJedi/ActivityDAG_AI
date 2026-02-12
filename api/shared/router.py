from __future__ import annotations

from typing import Dict, Any, Optional
import re

from .intent import classify_intent
from .schedule_graph import ScheduleGraph
from .analytics import (
    critical_path_summary,
    critical_and_near_critical,
    top_float_risks,
    project_duration,
    project_total_float,
)

# Matches:
# - numeric task ids (often 4+ digits in P6 exports)
# - task codes like A1030, EL12, CON2000, etc.
_TASK_ID_RE = re.compile(r"\b\d{4,}\b")
_TASK_CODE_RE = re.compile(r"\b[A-Z]{1,6}\d{1,6}\b")


def _find_task_by_code_or_id(tasks_df, token: str) -> Optional[Dict[str, Any]]:
    token = str(token).strip()

    # 1) Numeric task_id
    if "task_id" in tasks_df.columns and token.isdigit():
        m = tasks_df[tasks_df["task_id"].astype(str) == token]
        if len(m) > 0:
            return m.iloc[0].to_dict()

    # 2) Exact task_code
    if "task_code" in tasks_df.columns:
        m = tasks_df[tasks_df["task_code"].astype(str).str.upper() == token.upper()]
        if len(m) > 0:
            return m.iloc[0].to_dict()

    return None


def _extract_task_token(message: str) -> Optional[str]:
    """
    Extract either a task code (preferred) or a numeric task id from user text.
    Example: "What is float for CON2000" -> "CON2000"
             "show predecessors of 141301" -> "141301"
    """
    if not message:
        return None
    code = _TASK_CODE_RE.search(message.upper())
    if code:
        return code.group(0)
    tid = _TASK_ID_RE.search(message)
    if tid:
        return tid.group(0)
    return None


def _is_project_total_float_question(q: str) -> bool:
    """
    Detect "project-level" total float questions.
    We keep it simple and robust (all lowercase comparisons).
    """
    q = (q or "").lower()

    if "total float" not in q:
        return False

    # Common phrasing stakeholders use
    project_markers = [
        "project",
        "overall",
        "entire",
        "schedule",
        "job",
        "program",
    ]

    # If they explicitly ask "total float for the project/overall schedule"
    return any(m in q for m in project_markers)


def route_query(data, proj_id: str, message: str) -> Dict[str, Any]:
    """
    Routes a user message to the right schedule analytics function(s).

    Returns JSON-serializable dict for the UI (optionally later summarized by an LLM).
    """
    intent = classify_intent(message)
    q = (message or "").lower()

    # Build graph + project-scoped tasks
    sg = ScheduleGraph(data.tasks, data.taskpred, data.wbs)
    build = sg.build_for_project(proj_id)
    G = build.graph
    tasks = build.tasks

    # --- Project-level total float (handle BEFORE the generic FLOAT branch) ---
    if _is_project_total_float_question(q):
        counts = critical_and_near_critical(tasks).get("counts", {})
        return {
            "intent": "PROJECT_TOTAL_FLOAT",
            "project_id": str(proj_id),
            "project_total_float": project_total_float(tasks),
            "critical_near_counts": counts,
        }

    # --- Critical path ---
    if intent == "CRITICAL_PATH":
        res = critical_path_summary(G)
        return {"intent": intent, "project_id": str(proj_id), **res}

    # --- Duration / dates ---
    if intent == "DURATION":
        return {
            "intent": intent,
            "project_id": str(proj_id),
            "project_duration": project_duration(tasks),
        }

    # --- Float ---
    if intent == "FLOAT":
        token = _extract_task_token(message)

        # If they asked about a specific activity, return that activity’s float
        if token:
            t = _find_task_by_code_or_id(tasks, token)
            if t and "total_float_hr_cnt" in t:
                return {
                    "intent": "TASK_FLOAT",
                    "project_id": str(proj_id),
                    "task": {
                        "task_id": str(t.get("task_id", "")),
                        "task_code": str(t.get("task_code", "")),
                        "task_name": str(t.get("task_name", "")),
                        "wbs_name": str(t.get("wbs_name", "")),
                    },
                    "total_float_hr_cnt": t.get("total_float_hr_cnt"),
                }

        # Otherwise return top float risks + critical/near-critical buckets
        return {
            "intent": intent,
            "project_id": str(proj_id),
            "top_float_risks": top_float_risks(tasks),
            "critical_near": critical_and_near_critical(tasks),
            # Optional but helpful context:
            "project_total_float": project_total_float(tasks),
        }

    # --- Task neighborhood queries (pred/succ/lookup) ---
    if intent in ("PREDECESSORS", "SUCCESSORS", "TASK_LOOKUP"):
        token = _extract_task_token(message)
        if not token:
            return {
                "intent": intent,
                "project_id": str(proj_id),
                "note": "Please mention an activity/task code (e.g., CON2000) or a numeric task_id.",
            }

        t = _find_task_by_code_or_id(tasks, token)
        if not t:
            return {"intent": intent, "project_id": str(proj_id), "note": f"Task '{token}' not found in this project."}

        node_id = str(t.get("task_id", ""))
        if node_id not in G:
            return {
                "intent": intent,
                "project_id": str(proj_id),
                "task": t,
                "note": "Task found in table but not in dependency graph (no edges or missing IDs).",
            }

        if intent == "TASK_LOOKUP":
            preds = [
                {"task_id": p, "task_code": G.nodes[p].get("task_code", ""), "task_name": G.nodes[p].get("task_name", "")}
                for p in G.predecessors(node_id)
            ]
            succs = [
                {"task_id": s, "task_code": G.nodes[s].get("task_code", ""), "task_name": G.nodes[s].get("task_name", "")}
                for s in G.successors(node_id)
            ]
            return {"intent": intent, "project_id": str(proj_id), "task": t, "predecessors": preds[:50], "successors": succs[:50]}

        if intent == "PREDECESSORS":
            preds = [
                {"task_id": p, "task_code": G.nodes[p].get("task_code", ""), "task_name": G.nodes[p].get("task_name", "")}
                for p in G.predecessors(node_id)
            ]
            return {"intent": intent, "project_id": str(proj_id), "task": t, "predecessors": preds[:100]}

        # SUCCESSORS
        succs = [
            {"task_id": s, "task_code": G.nodes[s].get("task_code", ""), "task_name": G.nodes[s].get("task_name", "")}
            for s in G.successors(node_id)
        ]
        return {"intent": intent, "project_id": str(proj_id), "task": t, "successors": succs[:100]}

    # --- Health / Unknown: quick situation report ---
    return {
        "intent": intent,
        "project_id": str(proj_id),
        "project_duration": project_duration(tasks),
        "project_total_float": project_total_float(tasks),
        "critical_near": critical_and_near_critical(tasks),
        "top_float_risks": top_float_risks(tasks),
        "graph": {
            "tasks": int(G.number_of_nodes()),
            "relationships": int(G.number_of_edges()),
            "has_cycles": bool(build.has_cycles),
        },
    }
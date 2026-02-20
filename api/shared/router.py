from __future__ import annotations

"""
router.py — Query dispatcher for CriticalPath AI.

Routing strategy:
  SIMPLE / HIGH-CONFIDENCE queries → direct one-shot handler (fast, cheap)
  COMPLEX / AMBIGUOUS queries      → two-turn agent (powerful, thorough)

What makes a query "complex"?
  - Multiple intents detected (compound question)
  - Low classification confidence
  - UNKNOWN intent
  - Multi-hop reasoning needed
  - Intents that benefit from multi-tool reasoning (FLOAT, DATE_WINDOW, HEALTH)

Direct handlers are kept for speed. Anything nuanced goes to the agent.
The agent returns (answer_str, debug_info) — a pre-rendered string.
Direct handlers return a data dict for llm.py to render (existing flow).
"""


from typing import Dict, Any, Optional, List
from datetime import date
import re

from .intent import parse_query, QueryFrame
from .agent import run_agent
from .schedule_graph import ScheduleGraph
from .analytics import (
    list_all_activities,
    activities_in_window,
    float_risk_analysis,
    critical_path_summary,
    project_duration,
    project_total_float,
    critical_and_near_critical,
    float_by_phase,
)

# ---------------------------------------------------------------------------
# Routing decision thresholds
# ---------------------------------------------------------------------------

_DIRECT_INTENTS = {"LIST_ACTIVITIES", "CRITICAL_PATH", "DURATION", "PROJECT_TOTAL_FLOAT", "FLOAT", "PHASE_FLOAT", "HIGH_FLOAT"}
_AGENT_INTENTS  = {"UNKNOWN", "HEALTH", "DATE_WINDOW"}
_CONFIDENCE_THRESHOLD = 0.80


def _should_use_agent(qf: QueryFrame) -> bool:
    if qf.intent == "UNKNOWN":
        return True
    if len(qf.secondary_intents) > 0:   # compound question
        return True
    if qf.confidence < _CONFIDENCE_THRESHOLD:
        return True
    if qf.intent in _AGENT_INTENTS:
        return True
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project_tasks_with_wbs(data, proj_id: str):
    tasks = data.tasks[data.tasks["proj_id"].astype(str) == str(proj_id)].copy()
    if data.wbs is not None and "wbs_id" in tasks.columns and "wbs_id" in data.wbs.columns:
        w = data.wbs[["wbs_id", "wbs_name"]].drop_duplicates()
        tasks = tasks.merge(w, on="wbs_id", how="left")
    return tasks


def _find_task(tasks_df, token: str):
    token = str(token).strip()
    if "task_id" in tasks_df.columns and token.isdigit():
        m = tasks_df[tasks_df["task_id"].astype(str) == token]
        if not m.empty:
            return m.iloc[0].to_dict()
    if "task_code" in tasks_df.columns:
        m = tasks_df[tasks_df["task_code"].astype(str).str.upper() == token.upper()]
        if not m.empty:
            return m.iloc[0].to_dict()
    return None


def _build_graph(data, proj_id: str):
    sg = ScheduleGraph(data.tasks, data.taskpred, data.wbs)
    return sg.build_for_project(proj_id)


def _base_envelope(qf: QueryFrame, proj_id: str, routed_via: str) -> Dict[str, Any]:
    return {
        "intent": qf.intent,
        "secondary_intents": qf.secondary_intents,
        "confidence": qf.confidence,
        "classification_method": qf.classification_method,
        "routed_via": routed_via,
        "project_id": str(proj_id),
        "query_context": {
            "today": qf.meta.get("today"),
            "date_window": qf.date_window.to_dict() if qf.date_window else None,
            "task_token": qf.task_token,
            "top_n": qf.top_n,
        },
    }


# ---------------------------------------------------------------------------
# Direct handlers — fast, single-purpose, no agent overhead
# ---------------------------------------------------------------------------

def _direct_list_activities(data, proj_id, qf):
    result = _base_envelope(qf, proj_id, "direct")
    result["data"] = list_all_activities(_project_tasks_with_wbs(data, proj_id))
    return result


def _direct_critical_path(data, proj_id, qf):
    result = _base_envelope(qf, proj_id, "direct")
    build  = _build_graph(data, proj_id)
    result["data"] = critical_path_summary(build.graph)
    result["data"]["has_cycles"] = build.has_cycles
    return result

def _direct_phase_float(data, proj_id, qf):
    tasks = _project_tasks_with_wbs(data, proj_id)
    result = _base_envelope(qf, proj_id, "direct")
    phase = qf.meta.get("phase_filter", "")
    result["data"] = float_by_phase(tasks, 
                                    phase_filter=phase,
                                    near_critical_threshold_days=(qf.threshold_hours or 240.0) / 8.0,
                                    )
    return result

def _direct_high_float(data, proj_id, qf):
    tasks = _project_tasks_with_wbs(data, proj_id)
    result = _base_envelope(qf, proj_id, "direct")
    result["data"] = float_risk_analysis(
        tasks,
        near_critical_threshold_days=30.0,
    )
    return result


def _direct_duration(data, proj_id, qf):
    result = _base_envelope(qf, proj_id, "direct")
    result["data"] = {"project_duration": project_duration(_project_tasks_with_wbs(data, proj_id))}
    return result


def _direct_project_total_float(data, proj_id, qf):
    tasks  = _project_tasks_with_wbs(data, proj_id)
    result = _base_envelope(qf, proj_id, "direct")
    result["data"] = {
        "project_total_float": project_total_float(tasks),
        "critical_near": critical_and_near_critical(tasks, threshold_hours=qf.threshold_hours or 40.0),
    }
    return result


def _direct_task_lookup(data, proj_id, qf):
    tasks  = _project_tasks_with_wbs(data, proj_id)
    result = _base_envelope(qf, proj_id, "direct")
    if not qf.task_token:
        result["note"] = "Please specify a task code (e.g. CON2000) or numeric task ID."
        return result
    task = _find_task(tasks, qf.task_token)
    if not task:
        result["note"] = f"Task '{qf.task_token}' not found in project {proj_id}."
        return result
    build   = _build_graph(data, proj_id)
    G       = build.graph
    node_id = str(task.get("task_id", ""))
    preds, succs = [], []
    if node_id in G:
        preds = [{"task_id": p, "task_code": G.nodes[p].get("task_code",""), "task_name": G.nodes[p].get("task_name","")} for p in G.predecessors(node_id)]
        succs = [{"task_id": s, "task_code": G.nodes[s].get("task_code",""), "task_name": G.nodes[s].get("task_name","")} for s in G.successors(node_id)]
    result["data"] = {"task": task, "predecessors": preds[:100], "successors": succs[:100]}
    return result


def _direct_predecessors(data, proj_id, qf):
    tasks  = _project_tasks_with_wbs(data, proj_id)
    result = _base_envelope(qf, proj_id, "direct")
    if not qf.task_token:
        result["note"] = "Please specify a task code."
        return result
    task = _find_task(tasks, qf.task_token)
    if not task:
        result["note"] = f"Task '{qf.task_token}' not found."
        return result
    build   = _build_graph(data, proj_id)
    G       = build.graph
    node_id = str(task.get("task_id",""))
    preds   = []
    if node_id in G:
        preds = [{"task_id": p, "task_code": G.nodes[p].get("task_code",""), "task_name": G.nodes[p].get("task_name","")} for p in G.predecessors(node_id)]
    result["data"] = {"task": task, "predecessors": preds[:100]}
    return result

def _direct_float(data, proj_id, qf):
    tasks  = _project_tasks_with_wbs(data, proj_id)
    result = _base_envelope(qf, proj_id, "direct")
    result["data"] = float_risk_analysis(
        tasks,
        near_critical_threshold_days=(qf.threshold_hours or 240.0 )/8.0 # default 30 days
    )
    return result

def _direct_successors(data, proj_id, qf):
    tasks  = _project_tasks_with_wbs(data, proj_id)
    result = _base_envelope(qf, proj_id, "direct")
    if not qf.task_token:
        result["note"] = "Please specify a task code."
        return result
    task = _find_task(tasks, qf.task_token)
    if not task:
        result["note"] = f"Task '{qf.task_token}' not found."
        return result
    build   = _build_graph(data, proj_id)
    G       = build.graph
    node_id = str(task.get("task_id",""))
    succs   = []
    if node_id in G:
        succs = [{"task_id": s, "task_code": G.nodes[s].get("task_code",""), "task_name": G.nodes[s].get("task_name","")} for s in G.successors(node_id)]
    result["data"] = {"task": task, "successors": succs[:100]}
    return result


_DIRECT_HANDLERS = {
    "LIST_ACTIVITIES": _direct_list_activities,
    "CRITICAL_PATH": _direct_critical_path,
    "DURATION": _direct_duration,
    "FLOAT": _direct_float,
    "PROJECT_TOTAL_FLOAT": _direct_project_total_float,
    "TASK_LOOKUP": _direct_task_lookup,
    "PREDECESSORS": _direct_predecessors,
    "SUCCESSORS": _direct_successors,
    "PHASE_FLOAT": _direct_phase_float,
    "HIGH_FLOAT": _direct_high_float,
}

_NOT_IMPLEMENTED = {"CHANGE_SUMMARY", "SLIPPAGE", "RESOURCE_OVERALLOCATED"}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def route_query(
    data,
    proj_id: str,
    message: str,
    history: Optional[List[Dict[str, str]]] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Parse, classify, and route a user query.

    Returns a unified response dict. Two shapes:
      Agent path:  {..., "routed_via": "agent", "answer": str, "debug": dict}
      Direct path: {..., "routed_via": "direct", "data": dict}

    The caller (llm.py / API layer) checks "routed_via":
      - "agent"  → answer is already rendered, use it directly
      - "direct" → pass "data" to render_with_llm() as before

    Args:
        data:    ScheduleData object (tasks, taskpred, wbs)
        proj_id: P6 project ID string
        message: Raw user query
        history: Conversation history [{role, content}, ...]
        today:   ALWAYS pass date.today() from your API endpoint.
    """
    today = today or date.today()
    history = history or []
    qf = parse_query(message, today=today)

    # --- Agent path ---
    if _should_use_agent(qf):
        answer, debug = run_agent(
            data=data,
            proj_id=proj_id,
            message=message,
            history=history,
            today=today,
        )
        return {
            "intent": qf.intent,
            "secondary_intents": qf.secondary_intents,
            "confidence": qf.confidence,
            "classification_method": qf.classification_method,
            "routed_via": "agent",
            "project_id": str(proj_id),
            "query_context": {
                "today":  str(today),
                "date_window": qf.date_window.to_dict() if qf.date_window else None,
                "task_token": qf.task_token,
                "top_n": qf.top_n,
            },
            "answer": answer,
            "debug": debug,
        }

    # --- Direct path ---
    handler = _DIRECT_HANDLERS.get(qf.intent)
    if handler:
        return handler(data, proj_id, qf)

    # --- Not implemented ---
    if qf.intent in _NOT_IMPLEMENTED:
        result = _base_envelope(qf, proj_id, "not_implemented")
        result["note"] = (
            f"'{qf.intent}' analytics not yet implemented. "
            f"Date context: {qf.date_window.to_dict() if qf.date_window else None}"
        )
        return result

    # --- Final fallback: push to agent ---
    answer, debug = run_agent(data=data, proj_id=proj_id,
                              message=message, history=history, today=today)
    return {
        "intent": qf.intent,
        "routed_via": "agent_fallback",
        "project_id": str(proj_id),
        "answer": answer,
        "debug": debug,
    }
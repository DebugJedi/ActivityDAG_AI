from __future__ import annotations
from typing import Dict, Any, List
import re
import networkx as nx

from .intent import classify_intent
from .schedule_graph import ScheduleGraph
from .analytics import (
    critical_path_summary,
    critical_and_near_critical,
    top_float_risks,
    project_duration,
)

_TASK_ID_RE = re.compile(r"\b\d{4,}\b")
_TASK_CODE_RE = re.compile(r"\b[A-Z]{1,6}\d{1,6}\b")

def _find_task_by_code_or_id(tasks_df, token: str):
    token = str(token)
    if "task_id" in tasks_df.columns and token.isdigit():
        m = tasks_df[tasks_df["task_id"].astype(str) == token]
        if len(m) > 0:
            return m.iloc[0].to_dict()
    if "task_code" in tasks_df.columns:
        m = tasks_df[tasks_df["task_code"].astype(str) == token]
        if len(m) > 0:
            return m.iloc[0].to_dict()
    return None

def route_query(data, proj_id: str, message: str) -> Dict[str, Any]:
    intent = classify_intent(message)

    sg = ScheduleGraph(data.tasks, data.taskpred, data.wbs)
    build = sg.build_for_project(proj_id)
    G = build.graph
    tasks = build.tasks

    if intent == "CRITICAL_PATH":
        res = critical_path_summary(G)
        return {"intent": intent, **res}

    if intent == "FLOAT":
        # If user asked for float of a particular task, try lookup
        code = _TASK_CODE_RE.search(message)
        tid = _TASK_ID_RE.search(message)
        token = code.group(0) if code else (tid.group(0) if tid else None)
        if token:
            t = _find_task_by_code_or_id(tasks, token)
            if t and "total_float_hr_cnt" in t:
                return {"intent": intent, "task": token, "total_float_hr_cnt": t.get("total_float_hr_cnt"), "task_name": t.get("task_name")}
        # Otherwise return top risks + counts
        return {"intent": intent, "top_float_risks": top_float_risks(tasks), "critical_near": critical_and_near_critical(tasks)}

    if intent == "DURATION":
        return {"intent": intent, "project_duration": project_duration(tasks)}

    if intent in ("PREDECESSORS", "SUCCESSORS", "TASK_LOOKUP"):
        code = _TASK_CODE_RE.search(message)
        tid = _TASK_ID_RE.search(message)
        token = code.group(0) if code else (tid.group(0) if tid else None)
        if not token:
            return {"intent": intent, "note": "Please mention an activity/task code or numeric task_id."}
        t = _find_task_by_code_or_id(tasks, token)
        if not t:
            return {"intent": intent, "note": f"Task '{token}' not found in this project."}

        # Resolve to task_id (graph uses task_id)
        node_id = str(t.get("task_id"))
        if node_id not in G:
            return {"intent": intent, "task": t, "note": "Task found in table but not in dependency graph (no edges or missing IDs)."}

        if intent == "TASK_LOOKUP":
            # include neighborhood summary
            preds = [{"task_id": p, "task_code": G.nodes[p].get("task_code",""), "task_name": G.nodes[p].get("task_name","")} for p in G.predecessors(node_id)]
            succs = [{"task_id": s, "task_code": G.nodes[s].get("task_code",""), "task_name": G.nodes[s].get("task_name","")} for s in G.successors(node_id)]
            return {"intent": intent, "task": t, "predecessors": preds[:50], "successors": succs[:50]}

        if intent == "PREDECESSORS":
            preds = [{"task_id": p, "task_code": G.nodes[p].get("task_code",""), "task_name": G.nodes[p].get("task_name","")} for p in G.predecessors(node_id)]
            return {"intent": intent, "task": t, "predecessors": preds[:100]}

        succs = [{"task_id": s, "task_code": G.nodes[s].get("task_code",""), "task_name": G.nodes[s].get("task_name","")} for s in G.successors(node_id)]
        return {"intent": intent, "task": t, "successors": succs[:100]}

    # HEALTH or UNKNOWN: give a quick situation report
    return {
        "intent": intent,
        "project_duration": project_duration(tasks),
        "critical_near": critical_and_near_critical(tasks),
        "top_float_risks": top_float_risks(tasks),
        "graph": {"tasks": int(G.number_of_nodes()), "relationships": int(G.number_of_edges()), "has_cycles": build.has_cycles},
    }

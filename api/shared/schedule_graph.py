from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import pandas as pd
import networkx as nx
import math

def _to_float(v, default=0.0) -> float:
    try:
        if pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default

@dataclass
class GraphBuildResult:
    graph: nx.DiGraph
    tasks: pd.DataFrame
    preds: pd.DataFrame
    has_cycles: bool

class ScheduleGraph:
    """Builds a NetworkX DiGraph for a single P6 project."""

    def __init__(self, tasks: pd.DataFrame, preds: pd.DataFrame, wbs: Optional[pd.DataFrame] = None):
        self.tasks_all = tasks
        self.preds_all = preds
        self.wbs = wbs

    def build_for_project(self, proj_id: str) -> GraphBuildResult:
        tasks = self.tasks_all[self.tasks_all["proj_id"].astype(str) == str(proj_id)].copy()
        preds = self.preds_all[self.preds_all["proj_id"].astype(str) == str(proj_id)].copy()

        # Join WBS name if available
        if self.wbs is not None and "wbs_id" in tasks.columns and "wbs_id" in self.wbs.columns:
            w = self.wbs[["wbs_id", "wbs_name"]].drop_duplicates().copy()
            tasks = tasks.merge(w, on="wbs_id", how="left")

        G = nx.DiGraph()

        # Add nodes
        for _, t in tasks.iterrows():
            tid = str(t.get("task_id"))
            if tid == "None" or tid == "nan":
                continue
            dur_hr = _to_float(t.get("target_drtn_hr_cnt"), 0.0)
            tf_hr = _to_float(t.get("total_float_hr_cnt"), float("nan"))
            G.add_node(
                tid,
                task_code=str(t.get("task_code") or ""),
                task_name=str(t.get("task_name") or ""),
                wbs_name=str(t.get("wbs_name") or ""),
                duration_hr=dur_hr,
                total_float_hr=tf_hr if not math.isnan(tf_hr) else None,
                driving_path_flag=str(t.get("driving_path_flag") or ""),
            )

        # Add edges (pred -> succ)
        for _, r in preds.iterrows():
            u = str(r.get("pred_task_id"))
            v = str(r.get("task_id"))
            if u in G and v in G:
                lag_hr = _to_float(r.get("lag_hr_cnt"), 0.0)
                rel_type = str(r.get("pred_type") or "")
                G.add_edge(u, v, lag_hr=lag_hr, pred_type=rel_type)

        has_cycles = not nx.is_directed_acyclic_graph(G)
        return GraphBuildResult(graph=G, tasks=tasks, preds=preds, has_cycles=has_cycles)

def compute_cpm_times(G: nx.DiGraph) -> Dict[str, Dict[str, float]]:
    """Approx CPM (ES/EF) for DAGs only. Returns {task_id: {ES, EF}} in hours."""
    if not nx.is_directed_acyclic_graph(G):
        raise ValueError("Graph has cycles; CPM requires a DAG. Use P6-provided float fields instead.")

    order = list(nx.topological_sort(G))
    times: Dict[str, Dict[str, float]] = {n: {"ES": 0.0, "EF": 0.0} for n in order}

    for n in order:
        es = 0.0
        for p in G.predecessors(n):
            lag = float(G.edges[p, n].get("lag_hr", 0.0))
            pred_ef = times[p]["EF"]
            es = max(es, pred_ef + lag)
        dur = float(G.nodes[n].get("duration_hr", 0.0))
        times[n]["ES"] = es
        times[n]["EF"] = es + dur

    return times

def longest_time_path(G: nx.DiGraph) -> List[str]:
    """Returns a 'critical path' approximation for DAGs: path that maximizes EF."""
    times = compute_cpm_times(G)
    # Find sink with max EF
    end = max(times.keys(), key=lambda n: times[n]["EF"])
    # Backtrack: choose predecessor that achieved ES
    path = [end]
    cur = end
    while True:
        preds = list(G.predecessors(cur))
        if not preds:
            break
        # pick pred that maximizes EF + lag
        best = max(preds, key=lambda p: times[p]["EF"] + float(G.edges[p, cur].get("lag_hr", 0.0)))
        path.append(best)
        cur = best
    return list(reversed(path))

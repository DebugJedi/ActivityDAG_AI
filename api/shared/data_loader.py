from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from .blob_loader import load_csv_from_blob, list_blob_names


@dataclass
class ScheduleData:
    tasks: pd.DataFrame
    taskpred: pd.DataFrame
    wbs: Optional[pd.DataFrame]
    projects: Optional[pd.DataFrame]


def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.replace({"": pd.NA})
    df = df.dropna(how="all").reset_index(drop=True)
    return df


def _pick_name_by_suffix(names: list[str], suffix: str) -> Optional[str]:
    suffix_u = suffix.upper()
    matches = [n for n in names if n.upper().endswith(suffix_u)]
    if not matches:
        return None
    # deterministic pick
    return sorted(matches)[0]

def list_projects(data: ScheduleData) -> list[dict]:
    if data.projects is not None and "proj_id" in data.projects.columns:
        cols = [c for c in ["proj_id", "proj_short_name"] if c in data.projects.columns]
        projects = data.projects[cols].drop_duplicates().to_dict(orient="records")
        return [{"proj_id": p.get("proj_id", ""), "proj_name": p.get("proj_short_name", p.get("proj_id", ""))} for p in projects]
    if "proj_id" in data.tasks.columns:
        ids = data.tasks["proj_id"].dropna().unique().tolist()
        return [{"proj_id": pid, "proj_name": pid} for pid in ids]
    return []

# simple warm-instance cache (helps Azure Functions a lot)
_BLOB_CACHE: dict[tuple[str, str], ScheduleData] = {}


def load_schedule_data(data_dir: Path) -> ScheduleData:
    """
    Backwards compatible entry point.
    If P6_DATA_SOURCE=blob, ignores data_dir and loads from Azure Blob.
    Otherwise reads local CSVs from data_dir.
    """
    source = os.getenv("P6_DATA_SOURCE", "local").lower().strip()

    if source == "blob":
        container = os.getenv("P6_BLOB_CONTAINER", "").strip()
        prefix = os.getenv("P6_BLOB_PREFIX", "").strip()

        if not container:
            raise ValueError("P6_BLOB_CONTAINER is not set (required when P6_DATA_SOURCE=blob).")

        cache_key = (container, prefix)
        if cache_key in _BLOB_CACHE:
            return _BLOB_CACHE[cache_key]

        names = list_blob_names(container=container, prefix=prefix)

        tasks_name = _pick_name_by_suffix(names, "_TASK.csv")
        pred_name = _pick_name_by_suffix(names, "_TASKPRED.csv")
        wbs_name = _pick_name_by_suffix(names, "_PROJWBS.csv")
        proj_name = _pick_name_by_suffix(names, "_PROJECT.csv")

        if not tasks_name or not pred_name:
            raise FileNotFoundError(
                f"Missing required blobs in container='{container}' prefix='{prefix}'. "
                f"Need *_TASK.csv and *_TASKPRED.csv. Found: {len(names)} blobs."
            )

        tasks = _clean_df(load_csv_from_blob(container, tasks_name))
        taskpred = _clean_df(load_csv_from_blob(container, pred_name))
        wbs = _clean_df(load_csv_from_blob(container, wbs_name)) if wbs_name else None
        projects = _clean_df(load_csv_from_blob(container, proj_name)) if proj_name else None

        data = ScheduleData(tasks=tasks, taskpred=taskpred, wbs=wbs, projects=projects)
        _BLOB_CACHE[cache_key] = data
        return data

    # ---- local mode (current behavior) ----
    tasks_path = data_dir / "P01-1_TASK.csv"
    pred_path = data_dir / "P01-1_TASKPRED.csv"
    wbs_path = data_dir / "P01-1_PROJWBS.csv"
    proj_path = data_dir / "P01-1_PROJECT.csv"

    if not tasks_path.exists() or not pred_path.exists():
        raise FileNotFoundError(
            f"Missing required files. Expected at least {tasks_path.name} and {pred_path.name} in {data_dir}."
        )

    tasks = _clean_df(pd.read_csv(tasks_path, dtype=str, keep_default_na=False))
    taskpred = _clean_df(pd.read_csv(pred_path, dtype=str, keep_default_na=False))
    wbs = _clean_df(pd.read_csv(wbs_path, dtype=str, keep_default_na=False)) if wbs_path.exists() else None
    projects = _clean_df(pd.read_csv(proj_path, dtype=str, keep_default_na=False)) if proj_path.exists() else None

    return ScheduleData(tasks=tasks, taskpred=taskpred, wbs=wbs, projects=projects)

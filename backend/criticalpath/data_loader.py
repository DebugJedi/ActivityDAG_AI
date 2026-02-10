from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple
import pandas as pd

@dataclass
class ScheduleData:
    tasks: pd.DataFrame
    taskpred: pd.DataFrame
    wbs: Optional[pd.DataFrame]
    projects: Optional[pd.DataFrame]

def _read_csv(path: Path) -> pd.DataFrame:
    
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    
    df = df.replace({"": pd.NA})
    return df

def load_schedule_data(data_dir: Path) -> ScheduleData:

    #Need to automate picking files based on last part like _TASK, _TASKPRED ,_PROJWBS
    tasks_path = data_dir / "P01-1_TASK.csv"
    pred_path = data_dir / "P01-1_TASKPRED.csv"
    wbs_path = data_dir / "P01-1_PROJWBS.csv"
    proj_path = data_dir / "P01-1_PROJECT.csv"

    if not tasks_path.exists() or not pred_path.exists():
        raise FileNotFoundError(
            f"Missing required files. Expected at least {tasks_path.name} and {pred_path.name} in {data_dir}."
        )

    tasks = _read_csv(tasks_path)
    taskpred = _read_csv(pred_path)
    wbs = _read_csv(wbs_path) if wbs_path.exists() else None
    projects = _read_csv(proj_path) if proj_path.exists() else None

    # Drop pure blank rows (common in some exports)
    tasks = tasks.dropna(how="all").reset_index(drop=True)
    taskpred = taskpred.dropna(how="all").reset_index(drop=True)
    if wbs is not None:
        wbs = wbs.dropna(how="all").reset_index(drop=True)
    if projects is not None:
        projects = projects.dropna(how="all").reset_index(drop=True)

    return ScheduleData(tasks=tasks, taskpred=taskpred, wbs=wbs, projects=projects)

def list_projects(data: ScheduleData):
    
    # Prefer PROJECT table if available, else fall back to TASK.proj_id
    if data.projects is not None and "proj_id" in data.projects.columns:
        df = data.projects.dropna(subset=["proj_id"]).copy()
        # P6 often stores short name (e.g., P01-1) here:
        name_col = "proj_short_name" if "proj_short_name" in df.columns else None
        if name_col:
            df = df[["proj_id", name_col]].drop_duplicates()
            return [{"proj_id": str(r["proj_id"]), "proj_name": str(r[name_col])} for _, r in df.iterrows()]
        df = df[["proj_id"]].drop_duplicates()
        return [{"proj_id": str(r["proj_id"]), "proj_name": str(r["proj_id"])} for _, r in df.iterrows()]

    if "proj_id" in data.tasks.columns:
        proj_ids = (
            data.tasks.dropna(subset=["proj_id"])["proj_id"].astype(str).drop_duplicates().tolist()
        )
        return [{"proj_id": pid, "proj_name": pid} for pid in proj_ids]

    return []

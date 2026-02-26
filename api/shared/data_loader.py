from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from .blob_loader import load_csv_from_blob, list_blob_names




@dataclass
class ScheduleData:
    tasks: pd.DataFrame
    taskpred: pd.DataFrame
    wbs: Optional[pd.DataFrame] = None
    projects: Optional[pd.DataFrame] = None
    taskrsrc: Optional[pd.DataFrame] = None   
    rsrc: Optional[pd.DataFrame] = None       
    udftype: Optional[pd.DataFrame] = None
    udfvalue: Optional[pd.DataFrame] = None
    _loaded_full: bool = False


_LOCAL_CACHE: Optional[ScheduleData] = None 
_LOCAL_CACHE_LOCK = threading.Lock()

_BLOB_CACHE: dict[tuple[str, str], ScheduleData] = {}
_BLOB_CACHE_LOCK = threading.Lock() 

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

def _read_local(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    return _clean_df(pd.read_csv(path, dtype=str, keep_default_na=False))

def _read_blob(container: str, name: list[str], suffix: str) -> Optional[pd.DataFrame]:
    name = _pick_name_by_suffix(name, suffix)
    if not name:
        return None
    return _clean_df(load_csv_from_blob(container, name))

def list_projects(data: ScheduleData) -> list[dict]:
    if data.projects is not None and "proj_id" in data.projects.columns:
        cols = [c for c in ["proj_id", "proj_short_name"] if c in data.projects.columns]
        projects = data.projects[cols].drop_duplicates().to_dict(orient="records")
        return [{"proj_id": p.get("proj_id", ""), "proj_name": p.get("proj_short_name", p.get("proj_id", ""))} for p in projects]
    if "proj_id" in data.tasks.columns:
        ids = data.tasks["proj_id"].dropna().unique().tolist()
        return [{"proj_id": pid, "proj_name": pid} for pid in ids]
    return []


def _load_from_blob() -> ScheduleData:
    global _BLOB_CACHE

    container = os.getenv("P6_BLOB_CONTAINER", "").strip()
    prefix = os.getenv("P6_BLOB_PREFIX", "").strip()

    if not container:
        raise ValueError("P6_BLOB_CONTAINER is not set (required when P6_DATA_SOURCE=blob).")
    
    cache_key = (container, prefix)
    with _BLOB_CACHE_LOCK:
        if cache_key in _BLOB_CACHE:
            return _BLOB_CACHE[cache_key]
        
    names = list_blob_names(container=container, prefix=prefix)

    required_suffixes = {"tasks": "_TASK.csv", "taskpred": "_TASKPRED.csv"}
    optional_suffixes = {
        "wbs":      "_PROJWBS.csv",
        "projects": "_PROJECT.csv",
        "taskrsrc": "_TASKRSRC.csv",  
        "rsrc":     "_RSRC.csv",      
        "udftype":  "_UDFTYPE.csv",
        "udfvalue": "_UDFVALUE.csv",
    }

    for key , suffix in required_suffixes.items():
        if not _pick_name_by_suffix(names, suffix):
            raise FileNotFoundError(
                f"Missing required blob with suffix '{suffix}' in container='{container}' prefix='{prefix}'. "
                f"Found blobs: {names}"
            )
        
    results = {}

    def _load_blob(key: str, suffix: str):
        results[key] = _read_blob(container, names, suffix)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = []
        for key, suffix in {**required_suffixes, **optional_suffixes}.items():
            futures.append(pool.submit(_load_blob, key, suffix))
        for future in as_completed(futures):
            future.result()  # propagate exceptions

    data = ScheduleData(
        tasks=results.get("tasks"),
        taskpred=results.get("taskpred"),
        wbs=results.get("wbs"),
        projects=results.get("projects"),
        taskrsrc=results.get("taskrsrc"),  # ← correct
        rsrc=results.get("rsrc"),          # ← correct
        udftype=results.get("udftype"),
        udfvalue=results.get("udfvalue"),
        _loaded_full=True
    )



    with _BLOB_CACHE_LOCK:
        _BLOB_CACHE[cache_key] = data

    return data

_preload_thread: Optional[threading.Thread] = None
_preload_done = threading.Event()


def load_projects_only(data_dir: Path) -> list[dict]:
    """Loads only the PROJECT.csv to populate project dropdown, minimizing latency."""
    source = os.getenv("P6_DATA_SOURCE", "local").lower().strip()

    if source == "blob":
        container = os.getenv("P6_BLOB_CONTAINER", "").strip()
        prefix = os.getenv("P6_BLOB_PREFIX", "").strip()

        if not container:
            raise ValueError("P6_BLOB_CONTAINER is not set (required when P6_DATA_SOURCE=blob).")

        names = list_blob_names(container=container, prefix=prefix)
        proj_df = _read_blob(container, names, "_PROJECT.csv")
    else:
        proj_df = _read_local(data_dir / "P05-1_PROJECT.csv") 
        if proj_df is None:
            import glob 
            matches = list(data_dir.glob("*_PROJECT.csv"))
            proj_df = _clean_df(pd.read_csv(matches[0], dtype=str, keep_default_na=False)) if matches else None

    if proj_df is None:
        print(f"WARNING: No PROJECT.csv found in {'blob container ' + container if source == 'blob' else data_dir}. Project dropdown will be empty.")
        return []
    
    dummy = ScheduleData(
        
        projects=proj_df,
        tasks=pd.DataFrame(),
        taskpred=pd.DataFrame(),
        wbs=None,
        taskrsrc=None,    
        rsrc=None,       
        udftype=None,     
        udfvalue=None,   

    )
    return list_projects(dummy)


def preload_in_background(data_dir: Path) -> None:
    """Starts loading full schedule data in a background thread"""
    global _preload_thread

    if _preload_thread is not None:
        return 
    
    def _run():
        try:
            load_schedule_data(data_dir)
            print("[DataLoader] Background preload complete.")
        except Exception as e:
            print(f"[DataLoader] Background preload failed: {e}")
        finally:
            _preload_done.set()

    _preload_thread = threading.Thread(target=_run, daemon=True, name="Data-preloader")
    _preload_thread.start()
    print("[DataLoader] Started background preload thread.")

def wait_for_preload(timeout: Optional[float] = 10.0) -> bool:
    """
    Block until background preload is done or timeout expires.
    Returns True if data is ready, False if still loading."""

    return _preload_done.wait(timeout=timeout)



def load_schedule_data(data_dir: Path) -> ScheduleData:
    """
    Backwards compatible entry point.
    If P6_DATA_SOURCE=blob, ignores data_dir and loads from Azure Blob.
    Otherwise reads local CSVs from data_dir.
    """
    source = os.getenv("P6_DATA_SOURCE", "local").lower().strip()

    if source == "blob":
        return _load_from_blob()
    return _load_from_local(data_dir)

def _load_from_local(data_dir: Path) -> ScheduleData:
    global _LOCAL_CACHE

    with _LOCAL_CACHE_LOCK:
        if _LOCAL_CACHE is not None:
            return _LOCAL_CACHE

    all_csvs = list(data_dir.glob("*_*.csv"))
    suffix_map = {p.name.split("_", 1)[-1].upper(): p for p in all_csvs}

    task_path = _find_path(data_dir, suffix_map, "TASK.CSV")
    pred_path = _find_path(data_dir, suffix_map, "TASKPRED.CSV")

    if not task_path or not pred_path:
        raise FileNotFoundError(
            f"Missing required files (*_TASK.csv and *_TASKPRED.csv) in {data_dir}. "
            f"Found: {[p.name for p in all_csvs]}"
        )
    
    optional_suffixes = {
        "wbs":      "PROJWBS.CSV",
        "projects": "PROJECT.CSV",
        "taskrsrc": "TASKRSRC.CSV",  
        "rsrc":     "RSRC.CSV",      
        "udftype":  "UDFTYPE.CSV",
        "udfvalue": "UDFVALUE.CSV",
    }

    results = {"tasks": None, "taskpred": None}
    for key in optional_suffixes:
        results[key] = None
    
    def _load(key: str, path: Path):
        results[key] = _read_local(path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_load, "tasks", task_path): "tasks",
            pool.submit(_load, "taskpred", pred_path): "taskpred",
        }
        for key, suffix in optional_suffixes.items():
            path = _find_path(data_dir, suffix_map, suffix)
            if path:
                futures[pool.submit(_load, key, path)] = key
        for f in as_completed(futures):
            f.result()  
    
    data = ScheduleData(
        tasks=results["tasks"],
        taskpred=results["taskpred"],
        wbs=results.get("wbs"),
        projects=results.get("projects"),
        taskrsrc=results.get("taskrsrc"),  
        rsrc=results.get("rsrc"),          
        udftype=results.get("udftype"),
        udfvalue=results.get("udfvalue"),
    )
    with _LOCAL_CACHE_LOCK:
        _LOCAL_CACHE = data
    return data

def _find_path(data_dir: Path, suffix_map: dict, suffix_upper: str) -> Optional[Path]:
    """Find a CSV file by its suffix (case-insensitive)"""
    if suffix_upper in suffix_map:
        return suffix_map[suffix_upper]
    matches = list(data_dir.glob(f"*_{suffix_upper.replace('.CSV', '.csv')}"))
    if matches:
        return sorted(matches)[0]
    return None

# CriticalPath AI (local MVP)

A lightweight schedule-intelligence chatbot for Primavera P6 CSV exports.

## What it does
- You select a **project** (from `PROJECT.csv` / `TASK.csv`).
- You ask schedule questions like:
  - “Show critical path”
  - “Top float risks”
  - “Project duration”
  - “Predecessors of A1030”
- The backend **computes** answers (pandas + networkx) and (optionally) uses an LLM to **explain** them.

## Setup

### 1) Put your CSVs in `data/`
This repo expects files like:
- `TASK.csv`
- `TASKPRED.csv`
- `PROJWBS.csv` (optional)
- `PROJECT.csv` (optional)

You can also point to a different folder:
```bash
export CRITICALPATH_DATA_DIR=/absolute/path/to/your/csv
```

### 2) Create venv + install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3) (Optional) enable better English answers
Set an API key:
```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4o-mini"
```

The backend uses OpenAI's official Python SDK + Responses API when a key is present. (See OpenAI docs on platform.openai.com.)

### 4) Run
From repo root:
```bash
uvicorn backend.app:app --reload --port 8000
```
Open:
- http://localhost:8000

## Notes
- Sessions are kept in-memory (good for local MVP).
- CPM/critical-path is approximated for DAGs; if a cycle is detected we fall back to P6's `driving_path_flag` when present.

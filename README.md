# CriticalPath AI

> **P6 Schedule Intelligence Assistant — ask questions about your project schedule in plain English.**  
> Azure OpenAI · NetworkX · Azure Static Web Apps · Azure Functions · Python · Live in production

---

## What This Is

Project schedulers spend hours digging through Primavera P6 exports to answer basic questions — what's on the critical path, which activities have float risk, what are the predecessors of a given task. CriticalPath AI eliminates that entirely.

Upload your P6 CSV export, ask a question in plain English, and get an instant graph-computed answer with a natural language explanation powered by Azure OpenAI.

Built for and actively used on gas distribution pipeline project scheduling at a Fortune 500 utility.

---

## Demo

### Critical path analysis
![Critical Path](docs/screenshots/demo_critical_path.png)

### Date window query
![Date Window](docs/screenshots/demo_date_window.png)

### Baseline slippage + budget analysis
![Slippage and Budget](docs/screenshots/demo_budget.png)

---

## What You Can Ask

CriticalPath AI understands **12 intent types** out of the box. Below are real prompts and what each returns.

### Schedule & Critical Path

| Prompt | Intent | What it returns |
|---|---|---|
| `"Which activities are driving my project finish?"` | `CRITICAL_PATH` | Ordered list of zero-float activities forming the critical path + total duration |
| `"Show critical path"` | `CRITICAL_PATH` | Same as above, trigger phrase shortcut |
| `"What is the total project duration?"` | `DURATION` | Early finish of sink node in working days |
| `"Are any construction activities near critical?"` | `PHASE_FLOAT` | Critical (float=0) and near-critical (float≤30) activities filtered by phase |
| `"Which design tasks are at risk?"` | `PHASE_FLOAT` | Phase-specific float breakdown with critical/near-critical classification |
| `"Which permits have no float for this project?"` | `PHASE_FLOAT` | Permitting phase activities at zero float |

### Float & Resource Analysis

| Prompt | Intent | What it returns |
|---|---|---|
| `"Which tasks could slip without impacting the finish date?"` | `HIGH_FLOAT` | Top non-critical activities ranked by float descending |
| `"Which tasks can I delay if I need to reallocate resources?"` | `HIGH_FLOAT` | Same — float = scheduling flexibility for resource reallocation |
| `"Top float risks"` | `LOW_FLOAT` | Activities with lowest float — highest schedule risk |
| `"What tasks are assigned to the Civil Engineer?"` | `RESOURCE_TASKS` | Activities by resource name with float and criticality |

### Baseline & Budget

| Prompt | Intent | What it returns |
|---|---|---|
| `"Which activities have slipped from baseline?"` | `SLIPPAGE` | Behind/ahead counts, days of slippage, variance summary |
| `"What tasks are behind their original plan?"` | `SLIPPAGE` | Same — natural language variation handled |
| `"What is the total project budget?"` | `BUDGET_TOTAL` | Total budget split by Labor / Material / Equipment with % breakdown |
| `"Which activities have the highest budget?"` | `BUDGET_TOP_TASKS` | Top N activities ranked by budget with phase context |
| `"Show me the top 10 most expensive activities"` | `BUDGET_TOP_TASKS` | Ranked budget list with insights |

### Date Window Queries

| Prompt | Intent | What it returns |
|---|---|---|
| `"What activities are starting or finishing in the next 6 months?"` | `DATE_WINDOW` | Activities starting, finishing, and spanning the window with float |
| `"Show me near-critical activities starting next month"` | `DATE_WINDOW` | Date-filtered + float-filtered combined query |
| `"What tasks are starting in April 2026?"` | `DATE_WINDOW` | Month-specific activity lookup with critical path context |

---

## Architecture

```
Browser (Azure Static Web App)
    │
    ├── frontend/          →  HTML · CSS · JS chat interface
    │                         project switcher · version display
    └── POST /api/chat
            │
            ▼
    Azure Functions (Python)
    ├── Intent classifier  →  routes query to correct handler
    │   └── 12 intent types: CRITICAL_PATH · PHASE_FLOAT · HIGH_FLOAT
    │                         LOW_FLOAT · DATE_WINDOW · SLIPPAGE
    │                         BUDGET_TOTAL · BUDGET_TOP_TASKS
    │                         RESOURCE_TASKS · DURATION · ...
    ├── Graph engine       →  NetworkX DAG · CPM · float computation
    │   ├── critical_path()      forward + backward pass
    │   ├── float_analysis()     total float ranking
    │   ├── predecessors()       upstream dependency traversal
    │   └── phase_float()        WBS-filtered float analysis
    └── Azure OpenAI       →  natural language explanation layer
            │
            ▼
    Azure Blob Storage
    └── P6 CSV data        →  TASK.csv · TASKPRED.csv · PROJECT.csv
```

**Key design principle:** The LLM only explains, never computes. All schedule logic is computed deterministically by the graph engine. Azure OpenAI is invoked only to translate computed results into plain English — this eliminates hallucination risk on schedule data entirely.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend hosting | Azure Static Web Apps |
| Backend compute | Azure Functions (Python) |
| Graph engine | NetworkX — DAG construction, CPM, float |
| LLM layer | Azure OpenAI (GPT-4o) |
| Schedule data | Primavera P6 CSV exports |
| Data storage | Azure Blob Storage |
| CI/CD | GitHub Actions → Azure SWA |
| Dependency management | Poetry |

---

## Project Structure

```
ActivityDAG_AI/
├── frontend/                  ←  Static web app (HTML/CSS/JS)
│   └── index.html             ←  Chat UI, project switcher
├── api/                       ←  Azure Functions (Python)
│   ├── chat/                  ←  POST /api/chat — intent + routing
│   └── shared/
│       ├── graph_engine.py    ←  NetworkX DAG · CPM · float logic
│       └── intent.py          ←  Query classifier (12 intents)
├── data/                      ←  Your P6 CSV files go here (gitignored)
├── scripts/                   ←  Utility scripts
├── .github/workflows/         ←  CI/CD pipeline
├── staticwebapp.config.json
├── DEPLOYMENT.md
├── QUICKSTART.md
└── pyproject.toml
```

---

## Getting Started with Your Own P6 Data

### Step 1 — Export your P6 data

From Primavera P6, export the following tables as CSV:

| File | Required | Contents |
|---|---|---|
| `TASK.csv` | ✅ Yes | Activities, durations, float, dates |
| `TASKPRED.csv` | ✅ Yes | Predecessor relationships |
| `PROJECT.csv` | No | Project metadata |
| `PROJWBS.csv` | No | WBS hierarchy |

Place them in the `data/` directory:
```
ActivityDAG_AI/
└── data/
    ├── TASK.csv
    ├── TASKPRED.csv
    ├── PROJECT.csv       ← optional
    └── PROJWBS.csv       ← optional
```

Or point to a custom directory:
```bash
export CRITICALPATH_DATA_DIR=/absolute/path/to/your/csvs
```

---

### Step 2 — Install dependencies

```bash
# Clone the repo
git clone https://github.com/DebugJedi/ActivityDAG_AI.git
cd ActivityDAG_AI

# Install with Poetry
poetry install

# Or with pip
pip install -r requirements.txt
```

---

### Step 3 — Set up Azure OpenAI

You need an Azure OpenAI resource with a GPT-4o deployment.

1. Create an Azure OpenAI resource in [Azure Portal](https://portal.azure.com)
2. Deploy a `gpt-4o` model
3. Copy your endpoint and key

```bash
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
export AZURE_OPENAI_KEY="your-key"
export AZURE_OPENAI_DEPLOYMENT="gpt-4o"
```

> **No Azure OpenAI?** The system works without it — graph queries still compute correct answers, just without the natural language explanation layer.

---

### Step 4 — Run locally with Azure Functions emulator

```bash
# Install the SWA CLI
npm install -g @azure/static-web-apps-cli

# Start the local emulator (serves frontend + functions together)
swa start frontend --api-location api

# App available at:
# → http://localhost:4280
```

See [QUICKSTART.md](QUICKSTART.md) for more detailed local setup options.

---

## Deploying Your Own Instance on Azure

### Prerequisites
- Azure account
- Azure CLI installed (`brew install azure-cli`)
- GitHub account (for CI/CD)

### Step 1 — Create Azure resources

```bash
# Login
az login

# Create resource group
az group create --name criticalpath-rg --location westus2

# Create Storage Account for P6 data
az storage account create \
  --name criticalpathdataXXXX \
  --resource-group criticalpath-rg \
  --sku Standard_LRS

# Create blob container
az storage container create \
  --name p6-data \
  --account-name criticalpathdataXXXX
```

### Step 2 — Upload your P6 CSVs to Blob Storage

```bash
az storage blob upload-batch \
  --source ./data \
  --destination p6-data \
  --account-name criticalpathdataXXXX
```

### Step 3 — Create Azure Static Web App

1. Go to **Azure Portal → Static Web Apps → Create**
2. Connect to your GitHub fork of this repo
3. Set build settings:
   - App location: `frontend`
   - API location: `api`
   - Output location: *(leave blank)*
4. Copy the deployment token

### Step 4 — Add GitHub secrets

In your GitHub repo → Settings → Secrets → Actions, add:

```
AZURE_STATIC_WEB_APPS_API_TOKEN
AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_KEY
AZURE_OPENAI_DEPLOYMENT
AZURE_STORAGE_CONNECTION_STRING
BLOB_CONTAINER_NAME                ← p6-data
```

### Step 5 — Push and deploy

```bash
git push origin main
```

GitHub Actions will build and deploy automatically.

See [DEPLOYMENT.md](DEPLOYMENT.md) for advanced configuration options.

---

## Graph Engine Design

The core of this system is a **directed acyclic graph (DAG)** built from P6 predecessor relationships using NetworkX.

**Critical Path Method (CPM):**
- Forward pass computes Early Start / Early Finish for each node
- Backward pass computes Late Start / Late Finish
- Total float = Late Start − Early Start
- Critical path = all activities where float = 0

**Cycle handling:** If a cycle is detected in the schedule data (common with poorly exported P6 files), the engine falls back to P6's native `driving_path_flag` column when present — graceful degradation rather than a hard failure.

---

## Roadmap

- [x] Critical path computation
- [x] Float risk ranking (high + low float)
- [x] Phase-specific float analysis
- [x] Baseline slippage detection
- [x] Budget analysis by activity and resource
- [x] Date window queries (start/finish within range)
- [x] Resource assignment queries
- [x] Project switching in UI
- [ ] Baseline vs. actual variance chart
- [ ] Schedule health score dashboard
- [ ] Gantt chart visualization of critical path
- [ ] Multi-project portfolio view

---

## Author

Built and maintained by **Priyank Rao** — Data Scientist / ML Engineer  
[Portfolio](https://priyankrao.co) · [GitHub](https://github.com/DebugJedi)

---

*P6 project data is not included in this repository. Bring your own Primavera P6 CSV exports to run the system against your own schedules.*
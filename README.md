# CriticalPath AI

> **P6 Schedule Intelligence Assistant — ask questions about your project schedule in plain English.**  
> Azure OpenAI · NetworkX · Azure Static Web Apps · Azure Functions · Python

---

## What This Is

Project schedulers spend hours digging through Primavera P6 exports to answer basic questions — what's on the critical path, which activities have float risk, what are the predecessors of a given task. CriticalPath AI eliminates that entirely.

Upload your P6 CSV export, ask a question in plain English, and get an instant graph-computed answer with a natural language explanation powered by Azure OpenAI.

Built for and actively used on gas distribution pipeline project scheduling at a Fortune 500 utility.

---

## Key Capabilities

| Query | What it does |
|---|---|
| `"Show critical path"` | Computes longest path through the DAG, returns ordered activity list |
| `"Top float risks"` | Ranks activities by total float ascending — lowest float = highest risk |
| `"Project duration"` | Returns early finish of sink node in working days |
| `"Predecessors of A1030"` | Traverses graph edges, returns all upstream dependencies |
| `"Phase X float analysis"` | Filters by WBS phase, computes float distribution |
| `"High float activities"` | Returns activities above float threshold with context |

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
    ├── Graph engine       →  NetworkX DAG · CPM · float computation
    │   ├── critical_path()
    │   ├── float_analysis()
    │   ├── predecessors()
    │   └── phase_float()
    └── Azure OpenAI       →  natural language explanation layer
            │
            ▼
    Azure Blob Storage
    └── P6 CSV data        →  TASK.csv · TASKPRED.csv · PROJECT.csv
```

**Data flow:**
1. User selects project and types a schedule question
2. Azure Function classifies intent and routes to the correct graph query
3. NetworkX computes the answer directly from the P6 DAG
4. Azure OpenAI wraps the computed result in a clear natural language explanation
5. Response streams back to the chat interface

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
│       └── intent.py          ←  Query classifier
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
AZURE_STATIC_WEB_APPS_API_TOKEN    ← from Step 3
AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_KEY
AZURE_OPENAI_DEPLOYMENT
AZURE_STORAGE_CONNECTION_STRING    ← from Step 1
BLOB_CONTAINER_NAME                ← p6-data
```

### Step 5 — Push and deploy

```bash
git push origin main
```

GitHub Actions will build and deploy automatically. Your app will be live at the Azure Static Web Apps URL within a few minutes.

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

**Key design principle:** The LLM only explains, never computes. All schedule logic — critical path, float, predecessors — is computed deterministically by the graph engine. Azure OpenAI is invoked only to translate computed results into plain English. This eliminates hallucination risk on schedule data entirely.

---

## Why This Matters

Schedule analysis on large infrastructure projects is typically done manually by experienced planners using P6 directly. This tool makes that analysis:

- **Instant** — answers in seconds vs. hours of manual filtering
- **Accessible** — any project stakeholder can query the schedule without P6 access
- **Auditable** — graph-computed answers with full traceability

---

## Roadmap

- [x] Critical path computation
- [x] Float risk ranking
- [x] Predecessor/successor traversal
- [x] Phase-specific float analysis
- [x] Project switching in UI
- [ ] Baseline vs. actual variance analysis
- [ ] Schedule health score dashboard
- [ ] Gantt chart visualization of critical path
- [ ] Multi-project portfolio view

---

## Author

Built and maintained by **Priyank Rao** — Data Scientist / ML Engineer  
[Portfolio](https://priyankrao.co) · [GitHub](https://github.com/DebugJedi)

---

*P6 project data is not included in this repository. Bring your own Primavera P6 CSV exports to run the system against your own schedules.*
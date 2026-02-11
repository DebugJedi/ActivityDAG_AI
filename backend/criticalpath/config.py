import os
from pathlib import Path
from dotenv import load_dotenv

# Defaults assume you run from repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv()
DATA_DIR = Path(os.getenv("CRITICALPATH_DATA_DIR", REPO_ROOT / "data")).resolve()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # change if you like
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Keep sessions in-memory for MVP.
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))

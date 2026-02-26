import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Resolve data directory - works in both local dev and Azure
def _get_data_dir():
    if env_dir := os.getenv("CRITICAL_PATH_DATA_DIR"):
        return Path(env_dir)
    
    # Try relative path from this file
    relative_path = Path(__file__).parent.parent.parent / "data/exports"
    if relative_path.exists():
        return relative_path
    
    # Fallback for Azure: try from current working directory
    fallback = Path.cwd() / "data"
    if fallback.exists():
        return fallback
    
    # Last resort: return the relative path anyway (will error if files missing)
    return relative_path

DATA_DIR = _get_data_dir()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
AZURE_OPENAI_API_KEY=os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT=os.getenv("AZURE_OPENAI_ENDPOINT")

if __name__ == "__main__":
    print("Data Dir: ",DATA_DIR)
    print("OpenAI Model: ", OPENAI_MODEL)

import os
from pathlib import Path

from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = BASE_DIR / "monitor.db"


class Settings(BaseModel):
    api_key: str = os.getenv("MONITOR_API_KEY", "dev-monitor-key")
    database_url: str = os.getenv("MONITOR_DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
    recent_event_limit: int = int(os.getenv("MONITOR_RECENT_EVENT_LIMIT", "200"))


settings = Settings()

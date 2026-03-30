import os
from pathlib import Path

from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path(os.getenv("MONITOR_DATA_DIR", str(BASE_DIR)))
DEFAULT_DB_PATH = Path(os.getenv("MONITOR_DB_PATH", str(DEFAULT_DATA_DIR / "monitor.db")))


def _csv_env(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


class Settings(BaseModel):
    api_key: str = os.getenv("MONITOR_API_KEY", "")
    database_url: str = os.getenv("MONITOR_DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
    recent_event_limit: int = int(os.getenv("MONITOR_RECENT_EVENT_LIMIT", "200"))
    cors_allow_origins: list[str] = _csv_env("MONITOR_CORS_ALLOW_ORIGINS", "*")
    log_dir: str = os.getenv("MONITOR_LOG_DIR", str(Path("/tmp") / "shermon" / "logs"))
    log_file_name: str = os.getenv("MONITOR_LOG_FILE_NAME", "shermon.log")
    log_max_mb_default: int = int(os.getenv("MONITOR_LOG_MAX_MB", "50"))
    log_backup_count_default: int = int(os.getenv("MONITOR_LOG_BACKUP_COUNT", "20"))


settings = Settings()

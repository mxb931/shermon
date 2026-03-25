from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "client_ip"):
            record.client_ip = None
        if not hasattr(record, "request_id"):
            record.request_id = None
        if not hasattr(record, "message_type"):
            record.message_type = None
        if not hasattr(record, "source"):
            record.source = None
        if not hasattr(record, "state"):
            record.state = None
        if not hasattr(record, "event_id"):
            record.event_id = None
        return True


class CompactKeyValueFormatter(logging.Formatter):
    _FIELD_NAMES = ("client_ip", "request_id", "message_type", "source", "state", "event_id")

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        if self.usesTime():
            record.asctime = self.formatTime(record, self.datefmt)

        parts = [
            f"{record.asctime}",
            f"level={record.levelname}",
            f"logger={record.name}",
        ]

        for field in self._FIELD_NAMES:
            value = getattr(record, field, None)
            if value is None:
                continue
            text = str(value).strip()
            if not text or text == "-" or text.lower() == "null":
                continue
            parts.append(f"{field}={text}")

        parts.append(f"msg={record.message}")

        rendered = " ".join(parts)
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            if record.exc_text:
                rendered = f"{rendered}\n{record.exc_text}"
        return rendered


_LOGGING_READY = False


def configure_logging(log_dir: str, file_name: str, max_mb: int, backup_count: int) -> None:
    global _LOGGING_READY

    resolved_dir = Path(log_dir)
    resolved_dir.mkdir(parents=True, exist_ok=True)

    max_bytes = max(1, int(max_mb)) * 1024 * 1024
    backups = max(1, int(backup_count))
    log_path = resolved_dir / file_name

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    formatter = CompactKeyValueFormatter()
    context_filter = ContextFilter()

    file_handler = RotatingFileHandler(log_path, maxBytes=max_bytes, backupCount=backups)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(context_filter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(context_filter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    _LOGGING_READY = True


def logging_ready() -> bool:
    return _LOGGING_READY

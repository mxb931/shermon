from datetime import datetime


def status_from_event(event_type: str, severity: str) -> str:
    if event_type == "disable":
        return "white"
    if event_type == "enable":
        return "green"
    if event_type in {"ok", "recovery"}:
        return "green"
    if severity == "critical":
        return "red"
    if severity == "warning":
        return "yellow"
    return "green"


def is_active_alert_color(status_color: str) -> bool:
    return status_color in {"red", "yellow", "purple"}


def should_mark_active(event_type: str, status_color: str) -> bool:
    return event_type == "problem" and is_active_alert_color(status_color)


def updated_count(
    current: int,
    event_type: str,
    closed_for_entity: int = 0,
    deduplicated: bool = False,
    increment_active: bool = True,
) -> int:
    if event_type == "disable":
        return 0

    if event_type == "enable":
        return 0

    if event_type == "problem":
        if deduplicated or not increment_active:
            return current
        return current + 1

    if event_type in {"ok", "recovery"}:
        return max(0, current - closed_for_entity)

    return current


def should_change_state(last_color: str, next_color: str, event_time: datetime, last_changed_at: datetime) -> bool:
    if next_color != last_color:
        return True
    return event_time >= last_changed_at

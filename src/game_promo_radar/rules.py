from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

UNKNOWN_DISPLAY = "待确认"


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().upper() in {"", "NULL", "NAN", "NONE"}


def display_value(value: Any) -> Any:
    return UNKNOWN_DISPLAY if is_missing(value) else value


def deadline_status(deadline: str | None, today: date | None = None) -> str:
    if is_missing(deadline):
        return "待确认"
    today = today or date.today()
    end = datetime.fromisoformat(str(deadline)).date()
    days = (end - today).days
    if days < 0:
        return "已截止"
    if days <= 3:
        return "即将截止"
    return "进行中"


def lifecycle_status(start_time: str | None, deadline: str | None, today: date | None = None) -> str:
    today = today or date.today()
    start = None
    end = None
    if not is_missing(start_time):
        start = datetime.fromisoformat(str(start_time)).date()
    if not is_missing(deadline):
        end = datetime.fromisoformat(str(deadline)).date()
    if start and start > today:
        return "即将开始"
    if end:
        days = (end - today).days
        if days < 0:
            return "已截止"
        if days <= 3:
            return "即将截止"
        return "进行中"
    return "待确认"


def remaining_days(deadline: str | None, today: date | None = None) -> int | None:
    if is_missing(deadline):
        return None
    today = today or date.today()
    return (datetime.fromisoformat(str(deadline)).date() - today).days


def load_yaml_config(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_scoring_config(path: str | Path) -> dict[str, Any]:
    return load_yaml_config(path)

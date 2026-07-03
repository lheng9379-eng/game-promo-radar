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


def score_task(task: dict[str, Any], heat: dict[str, Any] | None, account_fit: bool, config: dict[str, Any]) -> float:
    weights = config["weights"]
    score = 0.0
    if not is_missing(task.get("unit_price")) or not is_missing(task.get("revenue_share")):
        score += weights["price_known"]
    status = deadline_status(task.get("deadline"))
    if status == "进行中":
        score += weights["deadline_days"]
    elif status == "即将截止":
        score += weights["deadline_days"] * 0.4
    if account_fit:
        score += weights["account_fit"]
    if heat:
        growth = float(heat.get("heat_growth") or 0)
        median_views = float(heat.get("median_views") or 0)
        growth_score = min(growth / config["heat"]["growth_full_score"], 1.0) * 0.5
        views_score = min(median_views / config["heat"]["median_views_full_score"], 1.0) * 0.5
        score += weights["heat_score"] * (growth_score + views_score)
    score += weights["source_confidence"] * float(task.get("confidence") or 0)
    return round(score, 2)


def calculate_estimated_income(task: dict[str, Any], metrics: dict[str, Any]) -> float | None:
    unit_price = task.get("unit_price")
    if is_missing(unit_price):
        return None
    task_type = task.get("task_type")
    if task_type == "CPM":
        return round((metrics.get("valid_views") or 0) / 1000 * float(unit_price), 2)
    if task_type == "CPA":
        return round((metrics.get("activations") or metrics.get("registrations") or 0) * float(unit_price), 2)
    if task_type == "CPT":
        return round(float(unit_price), 2)
    return None

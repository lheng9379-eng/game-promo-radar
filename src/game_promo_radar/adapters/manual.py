from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from game_promo_radar.models import Task
from game_promo_radar.rules import is_missing

REQUIRED_DEFAULTS = {
    "platform": "手动",
    "game_name": None,
    "task_name": "手动导入任务",
    "source_url": "manual://import",
}


def _optional_float(value: Any) -> float | None:
    if is_missing(value):
        return None
    return float(value)


def _optional_str(value: Any) -> str | None:
    if is_missing(value):
        return None
    return str(value)


def _optional_bool(value: Any) -> bool | None:
    if is_missing(value):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "是", "需要"}:
        return True
    if text in {"false", "0", "no", "n", "否", "不需要"}:
        return False
    return None


def task_from_row(row: dict) -> Task:
    data = {**REQUIRED_DEFAULTS, **{k: v for k, v in row.items() if not is_missing(v)}}
    return Task(
        platform=str(data["platform"]),
        game_name=_optional_str(data.get("game_name")),
        task_name=str(data["task_name"]),
        page_title=_optional_str(data.get("page_title")),
        reward_description=_optional_str(data.get("reward_description")),
        task_id=_optional_str(data.get("task_id")),
        task_type=str(data.get("task_type") or "普通创作激励"),
        billing_method=_optional_str(data.get("billing_method")),
        unit_price=_optional_float(data.get("unit_price")),
        revenue_share=_optional_float(data.get("revenue_share")),
        start_time=_optional_str(data.get("start_time")),
        deadline=_optional_str(data.get("deadline")),
        account_requirements=_optional_str(data.get("account_requirements")),
        material_url=_optional_str(data.get("material_url")),
        production_requirements=_optional_str(data.get("production_requirements")),
        requires_real_person=_optional_bool(data.get("requires_real_person")),
        requires_original_shooting=_optional_bool(data.get("requires_original_shooting")),
        requires_complex_editing=_optional_bool(data.get("requires_complex_editing")),
        signup_url=_optional_str(data.get("signup_url")),
        source_url=str(data["source_url"]),
        raw_snapshot=_optional_str(data.get("raw_snapshot")),
        confidence=float(data.get("confidence") or 0.4),
    )


def import_excel(path: str | Path) -> list[Task]:
    df = pd.read_excel(path)
    return [task_from_row(row) for row in df.to_dict("records")]


def export_excel(df: pd.DataFrame, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)

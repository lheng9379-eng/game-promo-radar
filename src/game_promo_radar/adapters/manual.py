from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from game_promo_radar.models import Task
from game_promo_radar.rules import is_missing

REQUIRED_DEFAULTS = {
    "platform": "手动",
    "game_name": "待确认",
    "task_name": "手动导入任务",
    "source_url": "manual://import",
    "task_category": "other",
    "settlement_type": "unknown",
    "content_form": "short_video",
    "is_game_related": False,
}

FIELD_ALIASES = {
    "任务名称": "task_name",
    "标题": "task_name",
    "任务标题": "task_name",
    "平台": "platform",
    "任务对象": "game_name",
    "对象": "game_name",
    "游戏名称": "game_name",
    "分类": "task_category",
    "任务分类": "task_category",
    "结算方式": "settlement_type",
    "奖励规则": "reward_rule_text",
    "结算规则": "reward_rule_text",
    "链接": "source_url",
    "任务链接": "source_url",
    "来源链接": "source_url",
    "截止时间": "deadline",
    "截止日期": "deadline",
    "风险备注": "risk_level",
    "作品形式": "content_form",
    "适合账号": "target_account_type",
    "是否游戏相关": "is_game_related",
    "单价": "unit_price",
    "分成比例": "revenue_share",
}

CATEGORY_ALIASES = {
    "游戏": "game",
    "游戏推广": "game",
    "app": "app",
    "App 推广": "app",
    "APP推广": "app",
    "电商": "ecommerce",
    "电商种草": "ecommerce",
    "本地生活": "local_life",
    "短剧": "short_drama",
    "影视短剧": "short_drama",
    "品牌": "brand",
    "品牌活动": "brand",
    "平台激励": "platform_incentive",
    "其他": "other",
}

SETTLEMENT_ALIASES = {
    "播放量": "play_count",
    "互动量": "interaction",
    "下载": "download",
    "下载/注册": "download",
    "注册": "download",
    "线索": "lead",
    "成交佣金": "sale_commission",
    "佣金": "sale_commission",
    "固定奖励": "fixed_reward",
    "奖金": "fixed_reward",
    "流量扶持": "traffic_support",
    "未知": "unknown",
}


def _optional_float(value: Any) -> float | None:
    if is_missing(value):
        return None
    return float(value)


def _optional_str(value: Any) -> str | None:
    if is_missing(value):
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if is_missing(value):
        return None
    return int(value)


def _optional_bool(value: Any) -> bool:
    if is_missing(value):
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "游戏", "game"}


def _normalize_choice(value: Any, aliases: dict[str, str], default: str) -> str:
    if is_missing(value):
        return default
    text = str(value).strip()
    return aliases.get(text, aliases.get(text.lower(), text))


def normalize_excel_row(row: dict) -> dict:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        target = FIELD_ALIASES.get(str(key).strip(), str(key).strip())
        normalized[target] = value
    if "task_category" in normalized:
        normalized["task_category"] = _normalize_choice(normalized["task_category"], CATEGORY_ALIASES, "other")
    if "settlement_type" in normalized:
        normalized["settlement_type"] = _normalize_choice(normalized["settlement_type"], SETTLEMENT_ALIASES, "unknown")
    return normalized


def task_from_row(row: dict) -> Task:
    row = normalize_excel_row(row)
    data = {**REQUIRED_DEFAULTS, **{k: v for k, v in row.items() if not is_missing(v)}}
    return Task(
        platform=str(data["platform"]),
        game_name=str(data["game_name"]),
        task_name=str(data["task_name"]),
        source_url=str(data["source_url"]),
        task_category=str(data.get("task_category") or "other"),
        settlement_type=str(data.get("settlement_type") or "unknown"),
        content_form=str(data.get("content_form") or "short_video"),
        target_account_type=_optional_str(data.get("target_account_type")),
        publish_platforms=_optional_str(data.get("publish_platforms")),
        reward_rule_text=_optional_str(data.get("reward_rule_text")),
        risk_level=_optional_str(data.get("risk_level")),
        difficulty_level=_optional_int(data.get("difficulty_level")),
        expected_value_score=_optional_int(data.get("expected_value_score")),
        account_match_score=_optional_int(data.get("account_match_score")),
        is_game_related=_optional_bool(data.get("is_game_related")),
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
        signup_url=_optional_str(data.get("signup_url")),
        raw_snapshot=_optional_str(data.get("raw_snapshot")),
        confidence=float(data.get("confidence") or 0.4),
    )


def import_excel(path: str | Path) -> list[Task]:
    df = pd.read_excel(path)
    return [task_from_row(row) for row in df.to_dict("records")]


def preview_excel(path: str | Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    rows = [task_from_row(row).to_record() for row in df.to_dict("records")]
    return pd.DataFrame(rows)


def export_excel(df: pd.DataFrame, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)

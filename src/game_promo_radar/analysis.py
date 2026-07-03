from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .rules import deadline_status, is_missing, lifecycle_status, remaining_days

FEASIBILITY_LABELS = {"推荐做", "可以做", "观望", "不建议做", "信息不足"}
DIFFICULTY_LABELS = {"简单", "一般", "较难", "困难", "无法判断"}


@dataclass
class TaskAnalysis:
    feasibility: str
    difficulty: str
    evidence: list[str]
    missing_fields: list[str]
    score: int
    difficulty_score: int


def _text(task: dict[str, Any]) -> str:
    parts = [
        task.get("task_name"),
        task.get("reward_description"),
        task.get("billing_method"),
        task.get("account_requirements"),
        task.get("production_requirements"),
        task.get("material_url"),
        task.get("public_heat_clues"),
        task.get("competition_clues"),
    ]
    return " ".join(str(x) for x in parts if not is_missing(x))


def _has_reward(task: dict[str, Any]) -> bool:
    return (
        not is_missing(task.get("unit_price"))
        or not is_missing(task.get("revenue_share"))
        or not is_missing(task.get("reward_description"))
    )


def _has_material(task: dict[str, Any]) -> bool:
    return not is_missing(task.get("material_url"))


def _config_value(config: dict[str, Any] | None, *keys: str, default: Any) -> Any:
    current: Any = config or {}
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def analyze_task(
    task: dict[str, Any],
    heat: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> TaskAnalysis:
    evidence: list[str] = []
    missing: list[str] = []
    score = 0
    difficulty_score = 0
    text = _text(task)
    high_heat_views = float(_config_value(config, "heat", "high_median_views", default=50000))
    short_deadline_days = int(_config_value(config, "deadline", "short_days", default=3))

    required = {
        "奖励": ("unit_price", "revenue_share"),
        "报名门槛": ("account_requirements",),
        "截止时间": ("deadline",),
        "素材": ("material_url",),
        "制作要求": ("production_requirements",),
    }
    for label, fields in required.items():
        if all(is_missing(task.get(field)) for field in fields):
            missing.append(label)

    if _has_reward(task):
        score += 25
        reward_parts = []
        if not is_missing(task.get("unit_price")):
            reward_parts.append(f"单价 {task.get('unit_price')}")
        if not is_missing(task.get("revenue_share")):
            reward_parts.append(f"分成 {task.get('revenue_share')}")
        if not is_missing(task.get("reward_description")):
            reward_parts.append(str(task.get("reward_description")))
        evidence.append(f"收益或奖励已公开：{'，'.join(reward_parts)}。")
    else:
        evidence.append("收益或奖励未获取到，不能推测。")

    status = deadline_status(task.get("deadline"))
    lifecycle = lifecycle_status(task.get("start_time"), task.get("deadline"))
    days = remaining_days(task.get("deadline"))
    if lifecycle == "已截止":
        score -= 40
        evidence.append("任务已截止。")
    elif lifecycle == "即将开始":
        score += 10
        evidence.append("任务尚未开始，但活动时间已公开。")
    elif lifecycle == "即将截止":
        score -= 5
        difficulty_score += 15
        evidence.append(f"剩余时间较短：{days} 天，少于或等于 {short_deadline_days} 天。")
    elif lifecycle == "进行中":
        score += 15
        evidence.append(f"仍在进行中，剩余 {days} 天。")
    else:
        evidence.append("截止时间未获取到。")

    if is_missing(task.get("account_requirements")):
        evidence.append("报名门槛未获取到。")
    else:
        req = str(task.get("account_requirements"))
        if any(word in req for word in ["无门槛", "不限", "0粉", "零粉"]):
            score += 15
            evidence.append("报名门槛较低。")
        elif any(word in req for word in ["万粉", "认证", "机构", "达人等级"]):
            score -= 10
            difficulty_score += 10
            evidence.append("报名门槛较高。")
        else:
            score += 5
            evidence.append("报名门槛已公开，但需要人工核对。")

    if _has_material(task):
        score += 10
        evidence.append("素材链接已公开。")
    else:
        difficulty_score += 10
        evidence.append("素材链接未获取到。")

    if is_missing(task.get("production_requirements")):
        difficulty_score += 10
        evidence.append("制作要求未获取到。")
    else:
        evidence.append("制作要求已公开。")

    hard_terms = {
        "真人出镜": 20,
        "出镜": 15,
        "原创拍摄": 20,
        "实拍": 15,
        "复杂剪辑": 15,
        "剧情": 10,
        "口播": 10,
        "配音": 8,
    }
    for term, weight in hard_terms.items():
        if term in text:
            difficulty_score += weight
            evidence.append(f"制作要求包含“{term}”。")

    if task.get("requires_real_person") is True:
        difficulty_score += 20
        evidence.append("页面明确要求真人出镜。")
    if task.get("requires_original_shooting") is True:
        difficulty_score += 20
        evidence.append("页面明确要求原创拍摄。")
    if task.get("requires_complex_editing") is True:
        difficulty_score += 15
        evidence.append("页面明确要求复杂剪辑。")

    if heat:
        median_views = heat.get("median_views")
        competition = heat.get("competition")
        if not is_missing(median_views):
            if float(median_views) >= high_heat_views:
                score += 10
                evidence.append("公开作品播放中位数较高。")
            else:
                evidence.append("公开作品播放中位数一般。")
        if competition == "high":
            score -= 5
            difficulty_score += 10
            evidence.append("同类作品竞争程度较高。")
        elif competition == "low":
            score += 5
            evidence.append("同类作品竞争程度较低。")
    else:
        if is_missing(task.get("public_heat_clues")):
            missing.append("公开作品热度")
        else:
            score += 5
            evidence.append(f"页面提供公开热度线索：{task.get('public_heat_clues')}。")
        if is_missing(task.get("competition_clues")):
            missing.append("同类作品竞争程度")
        else:
            difficulty_score += 5
            evidence.append(f"页面提供竞争程度线索：{task.get('competition_clues')}。")
        if is_missing(task.get("public_heat_clues")) and is_missing(task.get("competition_clues")):
            evidence.append("尚未接入公开作品热度和竞争数据。")

    if not is_missing(task.get("heat_trend")):
        if task.get("heat_trend") == "上升":
            score += 12
            evidence.append("游戏热度趋势上升。")
        elif task.get("heat_trend") == "下降":
            score -= 8
            evidence.append("游戏热度趋势下降。")
    if not is_missing(task.get("heat_index")):
        score += min(int(float(task.get("heat_index")) // 20), 10)
        evidence.append(f"已记录游戏热度指数：{task.get('heat_index')}。")
    if not is_missing(task.get("app_rank_position")):
        position = int(float(task.get("app_rank_position")))
        if position <= 20:
            score += 10
            evidence.append("榜单排名靠前，存在流量窗口。")
        elif position <= 100:
            score += 4
            evidence.append("榜单排名已记录，可作为参考。")
    if not is_missing(task.get("app_rank_change")) and float(task.get("app_rank_change")) > 0:
        score += 5
        evidence.append("榜单排名上升。")
    if task.get("ad_trend") == "增强":
        score += 10
        evidence.append("买量投放趋势增强。")
    elif task.get("ad_trend") == "减弱":
        score -= 5
        evidence.append("买量投放趋势减弱。")
    if not is_missing(task.get("ad_material_count")) and int(float(task.get("ad_material_count"))) >= 20:
        score += 6
        evidence.append("公开投放素材数量较多，疑似有推广预算。")
    if not is_missing(task.get("sample_count")) and int(float(task.get("sample_count"))) > 0:
        score += min(int(task.get("sample_count")) * 2, 8)
        evidence.append(f"已记录 {int(task.get('sample_count'))} 条同类样本，可参考打法。")
    if not is_missing(task.get("top_sample_like_count")) and int(float(task.get("top_sample_like_count"))) >= 1000:
        score += 6
        evidence.append("同类样本点赞较高，说明内容方向有验证。")
    if not is_missing(task.get("material_score")):
        material_score = int(float(task.get("material_score")))
        score += min(material_score, 12)
        difficulty_score -= min(material_score, 10)
        evidence.append(f"素材完整度评分 {material_score}，制作难度相应降低。")
    if not is_missing(task.get("risk_level")):
        risk = str(task.get("risk_level"))
        if risk == "高":
            score -= 35
            difficulty_score += 15
            evidence.append("风险等级为高，不建议优先投入。")
        elif risk == "中":
            score -= 15
            difficulty_score += 8
            evidence.append("风险等级为中，需要谨慎核对。")

    completeness = 1 - min(len(set(missing)) / 7, 1)
    score += round(completeness * 20)
    if completeness < 0.45:
        feasibility = "信息不足"
    elif score >= 65:
        feasibility = "推荐做"
    elif score >= 45:
        feasibility = "可以做"
    elif score >= 25:
        feasibility = "观望"
    else:
        feasibility = "不建议做"

    if "截止时间" in missing and feasibility in {"推荐做", "可以做"}:
        evidence.append("截止时间缺失，不能直接判断为推荐做或可以做。")
        feasibility = "观望"
    if lifecycle == "已截止" and feasibility != "信息不足":
        evidence.append("活动已截止，保留为历史情报，不参与推荐。")
        feasibility = "不建议做"

    if "制作要求" in missing and "素材" in missing:
        difficulty = "无法判断"
    elif difficulty_score < 15:
        difficulty = "简单"
    elif difficulty_score < 35:
        difficulty = "一般"
    elif difficulty_score < 55:
        difficulty = "较难"
    else:
        difficulty = "困难"

    return TaskAnalysis(feasibility, difficulty, evidence, sorted(set(missing)), score, difficulty_score)

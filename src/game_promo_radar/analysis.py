from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .rules import deadline_status, is_missing, remaining_days

FEASIBILITY_LABELS = {"推荐做", "可以做", "观望", "不建议做", "信息不足"}
DIFFICULTY_LABELS = {"简单", "一般", "较难", "困难", "无法判断"}
RISK_LABELS = {"low", "medium", "high"}

CATEGORY_ACCOUNT_HINTS = {
    "game": "游戏、测评、攻略、泛娱乐账号",
    "app": "工具、教程、效率、AI工具账号",
    "ecommerce": "好物、测评、生活方式账号",
    "local_life": "探店、本地生活、旅游账号",
    "short_drama": "影视、剧情、剪辑账号",
    "brand": "垂类达人、生活方式、泛娱乐账号",
    "platform_incentive": "对应平台活跃创作者账号",
    "other": "与任务主题匹配的垂类账号",
}


@dataclass
class TaskAnalysis:
    feasibility: str
    difficulty: str
    evidence: list[str]
    missing_fields: list[str]
    score: int
    difficulty_score: int
    risk_level: str
    expected_value_score: int
    account_match_score: int
    suitable_account_type: str
    worth_doing: bool


def _text(task: dict[str, Any]) -> str:
    parts = [
        task.get("task_name"),
        task.get("game_name"),
        task.get("task_category"),
        task.get("settlement_type"),
        task.get("target_account_type"),
        task.get("reward_rule_text"),
        task.get("billing_method"),
        task.get("account_requirements"),
        task.get("production_requirements"),
        task.get("material_url"),
    ]
    return " ".join(str(x) for x in parts if not is_missing(x))


def _has_reward(task: dict[str, Any]) -> bool:
    return not is_missing(task.get("unit_price")) or not is_missing(task.get("revenue_share"))


def _has_material(task: dict[str, Any]) -> bool:
    return not is_missing(task.get("material_url"))


def _risk_level(risk_score: int) -> str:
    if risk_score >= 45:
        return "high"
    if risk_score >= 20:
        return "medium"
    return "low"


def _difficulty_level(label: str, difficulty_score: int) -> int | None:
    if label == "无法判断":
        return None
    if label == "简单":
        return 1
    if label == "一般":
        return 2 if difficulty_score < 25 else 3
    if label == "较难":
        return 4
    return 5


def _clamp_score(value: int) -> int:
    return max(1, min(value, 100))


def _split_tags(value: Any) -> set[str]:
    if is_missing(value):
        return set()
    text = str(value)
    for sep in ["，", "、", "/", "|", ";", "；"]:
        text = text.replace(sep, ",")
    return {item.strip().lower() for item in text.split(",") if item.strip()}


def _account_match(
    task: dict[str, Any],
    account_profile: dict[str, Any] | None,
    category: str,
    content_form: str,
    text: str,
) -> tuple[int, list[str]]:
    if not account_profile:
        base = 55
        if task.get("is_game_related") or category == "game":
            base += 10
        if not is_missing(task.get("target_account_type")):
            base += 20
        return base, ["未选择账号画像，按任务分类给出通用账号建议。"]

    reasons: list[str] = []
    score = 45
    platform = str(task.get("platform") or "").lower()
    account_platform = str(account_profile.get("platform") or "").lower()
    if platform and account_platform and platform == account_platform:
        score += 15
        reasons.append("账号平台与任务平台一致。")
    elif account_platform:
        score -= 8
        reasons.append("账号平台与任务平台不完全一致，需要确认能否发布。")

    acceptable = _split_tags(account_profile.get("acceptable_categories"))
    domain_tags = _split_tags(account_profile.get("account_domain"))
    target_tags = _split_tags(task.get("target_account_type"))
    if category in acceptable:
        score += 25
        reasons.append("任务分类在账号可承接范围内。")
    elif target_tags & domain_tags:
        score += 18
        reasons.append("任务适合账号类型与账号领域匹配。")
    else:
        score -= 12
        reasons.append("任务分类或账号领域匹配度偏弱。")

    account_forms = _split_tags(account_profile.get("content_forms"))
    if content_form in account_forms:
        score += 12
        reasons.append("账号擅长该作品形式。")
    elif account_forms:
        score -= 6
        reasons.append("任务作品形式不是账号主要擅长形式。")

    if any(term in text for term in ["真人出镜", "出镜", "实拍", "口播"]):
        if bool(account_profile.get("real_person")):
            score += 10
            reasons.append("账号支持真人出镜要求。")
        else:
            score -= 18
            reasons.append("任务可能需要真人出镜，账号画像未标记支持。")

    average_views = account_profile.get("average_views")
    follower_count = account_profile.get("follower_count")
    if not is_missing(average_views) and int(average_views) >= 10000:
        score += 8
        reasons.append("账号平均播放具备基础承接能力。")
    if not is_missing(follower_count) and int(follower_count) >= 10000:
        score += 5
        reasons.append("账号粉丝量达到常见任务门槛。")
    return score, reasons


def analyze_task(
    task: dict[str, Any],
    heat: dict[str, Any] | None = None,
    account_profile: dict[str, Any] | None = None,
) -> TaskAnalysis:
    evidence: list[str] = []
    missing: list[str] = []
    score = 0
    difficulty_score = 0
    risk_score = 0
    text = _text(task)
    category = str(task.get("task_category") or "game")
    settlement_type = str(task.get("settlement_type") or "unknown")
    content_form = str(task.get("content_form") or "short_video")

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
        evidence.append("收益或奖励已公开。")
    else:
        risk_score += 10
        evidence.append("收益或奖励未获取到，不能推测。")

    if not is_missing(task.get("reward_rule_text")) or settlement_type != "unknown":
        score += 8
        evidence.append("结算方式或原始规则已记录。")
    else:
        risk_score += 15
        missing.append("结算规则")
        evidence.append("结算规则不清晰，需要人工确认。")

    status = deadline_status(task.get("deadline"))
    days = remaining_days(task.get("deadline"))
    if status == "已截止":
        score -= 40
        evidence.append("任务已截止。")
    elif status == "即将截止":
        score -= 5
        difficulty_score += 15
        evidence.append(f"剩余时间较短：{days} 天。")
    elif status == "进行中":
        score += 15
        evidence.append(f"仍在进行中，剩余 {days} 天。")
    else:
        evidence.append("截止时间未获取到。")

    if is_missing(task.get("account_requirements")):
        risk_score += 5
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

    risk_terms = {
        "刷量": 80,
        "互粉": 55,
        "互赞": 55,
        "虚假互动": 80,
        "搬运": 55,
        "侵权": 80,
        "灰产": 90,
        "诈骗": 90,
        "违规引流": 80,
        "垫资": 35,
        "私域": 25,
        "保证收益": 30,
    }
    for term, weight in risk_terms.items():
        if term in text:
            risk_score += weight
            evidence.append(f"发现风险词“{term}”，不应采集或推荐违规任务。")

    uncertain_terms = ["按平台最终审核", "结算不保证", "规则可能调整", "名额有限", "人工审核", "待定"]
    if settlement_type == "unknown":
        risk_score += 15
        evidence.append("结算方式未知，存在较高结算不确定性。")
    for term in uncertain_terms:
        if term in text:
            risk_score += 12
            evidence.append(f"结算或规则包含不确定描述“{term}”。")

    if str(task.get("platform") or "") in {"抖音", "快手", "小红书", "B站", "TapTap"}:
        score += 4
        evidence.append("来源平台属于已知内容平台。")

    if heat:
        median_views = heat.get("median_views")
        competition = heat.get("competition")
        if not is_missing(median_views):
            if float(median_views) >= 50000:
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
        missing.append("公开作品热度")
        missing.append("同类作品竞争程度")
        evidence.append("尚未接入公开作品热度和竞争数据。")

    completeness = 1 - min(len(set(missing)) / 7, 1)
    score += round(completeness * 20)
    risk_level = str(task.get("risk_level") or _risk_level(risk_score))
    if risk_level == "high":
        score -= 45
    elif risk_level == "medium":
        score -= 10

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

    suitable_account = task.get("target_account_type")
    if is_missing(suitable_account):
        suitable_account = CATEGORY_ACCOUNT_HINTS.get(category, CATEGORY_ACCOUNT_HINTS["other"])
    account_match_score = task.get("account_match_score")
    account_reasons: list[str] = []
    if is_missing(account_match_score):
        account_match_score, account_reasons = _account_match(
            task,
            account_profile,
            category,
            content_form,
            text,
        )
        evidence.extend(account_reasons)
    elif account_profile:
        _, account_reasons = _account_match(task, account_profile, category, content_form, text)
        evidence.extend(account_reasons)
    expected_value_score = task.get("expected_value_score")
    if is_missing(expected_value_score):
        expected_value_score = score
    if int(account_match_score) < 45:
        evidence.append("账号匹配度偏低，不建议作为当前账号优先任务。")
    worth_doing = feasibility in {"推荐做", "可以做"} and risk_level != "high" and int(account_match_score) >= 45

    return TaskAnalysis(
        feasibility,
        difficulty,
        evidence,
        sorted(set(missing)),
        score,
        difficulty_score,
        risk_level,
        _clamp_score(int(expected_value_score)),
        _clamp_score(int(account_match_score)),
        str(suitable_account),
        worth_doing,
    )

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import re
from typing import Any
from urllib.parse import urlparse

from .models import normalize_source_url, now_iso
from .rules import is_missing, lifecycle_status, remaining_days


DISCOVERY_KEYWORDS = [
    "创作者招募",
    "创作者激励计划",
    "内容征集",
    "视频征集",
    "投稿奖励",
    "投稿赢现金",
    "发行人计划",
    "推广任务",
    "达人招募",
    "博主招募",
    "品牌合作",
    "创作大赛",
    "瓜分奖金",
    "现金激励",
    "流量激励",
    "UGC征集",
    "创作者应援计划",
    "游戏推广",
    "短剧推广",
    "APP推广",
    "按播放量结算",
]

SEARCH_DISCOVERY_KEYWORDS = [
    "创作者招募",
    "投稿奖励",
    "视频征集",
    "内容征集",
    "创作大赛",
    "达人招募",
    "博主招募",
    "发行人计划",
    "游戏推广",
    "短剧推广",
    "APP推广",
    "现金激励",
    "瓜分奖金",
    "按播放量结算",
]

SEARCH_DISCOVERY_TERMS = ["游戏", "手游", "短剧", "APP", "品牌", "抖音", "快手", "小红书", "B站", "微博", "TapTap"]

DEFAULT_INDUSTRY_TERMS = ["游戏", "手游", "新游", "APP", "短剧", "品牌活动", "内容推广"]
DEFAULT_PLATFORM_TERMS = ["抖音", "快手", "小红书", "B站", "微博", "知乎", "视频号", "TapTap", "好游快爆"]

CREATOR_ACTION_TERMS = ["投稿", "发布", "创作", "视频", "图文", "内容", "带话题", "挂载", "征集", "报名"]
REWARD_TERMS = ["奖励", "奖金", "现金", "稿费", "结算", "佣金", "分成", "保底", "阶梯", "播放量", "流量扶持"]
REGISTRATION_TERMS = ["报名", "参与方式", "投稿入口", "报名入口", "申请", "立即参与", "填写问卷", "活动规则"]
AGENCY_AD_TERMS = ["培训", "课程", "代运营", "招商加盟", "收徒", "引流课", "陪跑"]
PAYMENT_RISK_TERMS = ["先付费", "押金", "保证金", "私人转账", "私下转账", "加微信付款", "仅私信", "个人微信"]
PRIVATE_CONTACT_TERMS = ["私人微信", "个人微信", "加V", "加v", "私聊", "私信领取"]
EXAGGERATED_TERMS = ["日入过万", "稳赚", "躺赚", "零风险", "暴富"]

OFFICIAL_HOST_HINTS = {
    "douyin.com": "A",
    "gamepublisher.cn": "A",
    "oceanengine.com": "A",
    "kuaishou.com": "A",
    "xiaohongshu.com": "A",
    "bilibili.com": "A",
    "weibo.com": "B",
    "zhihu.com": "B",
    "qq.com": "B",
    "taptap.cn": "B",
    "3839.com": "B",
}

RECOMMENDATIONS = ["强烈推荐", "推荐做", "可以尝试", "观望", "不建议", "信息不足", "高风险"]
CAMPAIGN_STATUSES = [
    "新发现",
    "待验证",
    "有效",
    "准备报名",
    "已报名",
    "制作中",
    "已发布",
    "数据观察中",
    "待结算",
    "已结算",
    "已过期",
    "不符合条件",
    "疑似风险",
]


@dataclass
class CampaignScore:
    score: float
    recommendation: str
    reasons: list[str]
    expected_income: float | None
    estimated_production_hours: float | None
    expected_hourly_income: float | None


def campaign_candidate_id(source_url: str | None, campaign_name: str | None = None, publisher_name: str | None = None) -> str:
    basis = normalize_source_url(source_url) if source_url else f"{publisher_name or ''}|{campaign_name or ''}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20]


def generate_keyword_queries(
    games: list[str] | None = None,
    brands: list[str] | None = None,
    platforms: list[str] | None = None,
    industry_terms: list[str] | None = None,
    max_queries: int = 160,
) -> list[str]:
    games = [x for x in (games or []) if x]
    brands = [x for x in (brands or []) if x]
    platforms = platforms or DEFAULT_PLATFORM_TERMS
    industry_terms = industry_terms or DEFAULT_INDUSTRY_TERMS
    subjects = list(dict.fromkeys(games + brands + industry_terms))
    queries: list[str] = []
    for keyword in DISCOVERY_KEYWORDS:
        for subject in subjects:
            queries.append(f"{subject} {keyword}")
        for platform in platforms:
            queries.append(f"{platform} {keyword}")
    return list(dict.fromkeys(queries))[:max_queries]


def generate_search_discovery_queries(max_queries: int = 80) -> list[str]:
    queries = [f"{term} {keyword}" for term in SEARCH_DISCOVERY_TERMS for keyword in SEARCH_DISCOVERY_KEYWORDS]
    return list(dict.fromkeys(queries))[:max_queries]


def source_reliability_for_url(url: str | None, publisher_type: str | None = None, configured_level: str | None = None) -> str:
    if configured_level in {"A", "B", "C", "D", "E"}:
        return configured_level
    host = urlparse(str(url or "")).netloc.lower()
    for hint, level in OFFICIAL_HOST_HINTS.items():
        if host.endswith(hint):
            if publisher_type in {"代理商", "MCN", "服务商"} and level in {"A", "B"}:
                return "C"
            return level
    if publisher_type in {"平台"}:
        return "A"
    if publisher_type in {"品牌", "游戏厂商"}:
        return "B"
    if publisher_type in {"代理商", "MCN", "服务商"}:
        return "C"
    return "D"


def detect_risk_signals(text: str, source_url: str | None = None, registration_url: str | None = None, reliability: str | None = None) -> tuple[str, list[str]]:
    signals: list[str] = []
    for term in PAYMENT_RISK_TERMS + PRIVATE_CONTACT_TERMS + EXAGGERATED_TERMS:
        if term.lower() in text.lower():
            signals.append(term)
    if "活动规则" not in text and "规则" not in text:
        signals.append("没有活动规则")
    if not any(term in text for term in ["结算主体", "主办方", "官方", "平台", "品牌"]):
        signals.append("没有结算主体")
    if source_url and registration_url:
        source_host = urlparse(source_url).netloc.lower()
        reg_host = urlparse(registration_url).netloc.lower()
        if source_host and reg_host and source_host != reg_host and reliability in {"A", "B"}:
            signals.append("报名域名与官方主体不一致")
    if reliability in {"D", "E"}:
        signals.append("低可信来源")
    if any(term in signals for term in PAYMENT_RISK_TERMS) or "押金" in signals or "私人转账" in signals:
        return "高", list(dict.fromkeys(signals))
    if signals:
        return "中" if reliability not in {"D", "E"} else "高", list(dict.fromkeys(signals))
    return "低", []


def validate_candidate(record: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    text = " ".join(str(record.get(key) or "") for key in ["campaign_name", "raw_text", "reward_model", "account_requirements", "publish_requirements", "material_requirements"])
    reliability = source_reliability_for_url(record.get("source_url"), record.get("publisher_type"), record.get("source_reliability"))
    risk_level, risk_signals = detect_risk_signals(text, record.get("source_url"), record.get("registration_url"), reliability)
    checks = {
        "要求创作者发布内容": any(term in text for term in CREATOR_ACTION_TERMS),
        "存在奖励或结算规则": any(term in text for term in REWARD_TERMS) or not is_missing(record.get("reward_min")) or not is_missing(record.get("reward_pool")),
        "官方或可信发布主体": reliability in {"A", "B", "C"},
        "存在报名入口": not is_missing(record.get("registration_url")) or any(term in text for term in REGISTRATION_TERMS),
        "仍在有效期": lifecycle_status(None, record.get("deadline"), today=today) != "已截止",
        "不是培训广告或代运营广告": not any(term in text for term in AGENCY_AD_TERMS),
        "未发现付费押金或私人转账": not any(term in text for term in PAYMENT_RISK_TERMS),
    }
    passed = all(checks.values()) and risk_level != "高"
    status = "验证通过" if passed else ("疑似风险" if risk_level == "高" else "待验证")
    notes = "；".join(f"{key}:{'是' if value else '否'}" for key, value in checks.items())
    return {
        **record,
        "source_reliability": reliability,
        "risk_level": risk_level,
        "risk_signals": "、".join(risk_signals) or None,
        "status": status,
        "validation_notes": notes,
        "last_verified_at": now_iso(),
    }


def parse_reward_numbers(text: str | None) -> dict[str, float | None]:
    if is_missing(text):
        return {"reward_min": None, "reward_max": None, "reward_pool": None}
    values = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*元", str(text))]
    pool = None
    pool_match = re.search(r"(?:奖池|瓜分|总奖金)[^\d]*(\d+(?:\.\d+)?)\s*(万)?元", str(text))
    if pool_match:
        pool = float(pool_match.group(1)) * (10000 if pool_match.group(2) else 1)
    return {
        "reward_min": min(values) if values else None,
        "reward_max": max(values) if values else None,
        "reward_pool": pool,
    }


def candidate_activity_signals(text: str) -> dict[str, bool]:
    return {
        "要求发布作品": any(term in text for term in CREATOR_ACTION_TERMS),
        "存在奖励": any(term in text for term in REWARD_TERMS),
        "存在报名": any(term in text for term in REGISTRATION_TERMS),
        "存在截止时间": bool(re.search(r"(20\d{2}[-/年.]\s*\d{1,2}[-/月.]\s*\d{1,2}|截止|截至|活动时间|报名时间)", text)),
        "存在活动词": any(term in text for term in ["创作者", "投稿", "达人", "征集", "招募", "创作大赛", "活动"]),
    }


def should_save_candidate_loose(title: str | None, snippet: str | None = None, detail_text: str | None = None) -> tuple[bool, str]:
    text = " ".join(str(x or "") for x in [title, snippet, detail_text])
    if not text.strip():
        return False, "no_title_snippet_or_detail"
    if any(term in text for term in AGENCY_AD_TERMS):
        return False, "training_or_agency_ad"
    if any(term in text for term in ["外挂", "博彩", "刷量", "黑产", "破解"]):
        return False, "illegal_or_blackhat"
    signals = candidate_activity_signals(text)
    hit_count = sum(1 for value in signals.values() if value)
    if hit_count >= 2:
        return True, "matched_two_activity_signals"
    if hit_count == 1:
        return False, "only_one_activity_signal"
    return False, "not_activity_page"


def candidate_from_discovery(
    *,
    source_url: str,
    title: str | None,
    snippet: str | None = None,
    detail_text: str | None = None,
    source_id: str | None = None,
    source_platform: str | None = None,
    content_platform: str | None = None,
    raw_snapshot: str | None = None,
    configured_reliability: str | None = None,
) -> dict[str, Any]:
    text = " ".join(str(x or "") for x in [title, snippet, detail_text])
    reward_numbers = parse_reward_numbers(text)
    deadline_match = re.findall(r"(20\d{2})[-/年.]\s*(\d{1,2})[-/月.]\s*(\d{1,2})", text)
    deadline = None
    if deadline_match:
        year, month, day = deadline_match[-1]
        deadline = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    reward_sentence = None
    for sentence in re.split(r"[。；;\n]", text):
        if any(term in sentence for term in REWARD_TERMS):
            reward_sentence = sentence.strip()[:240]
            break
    account_sentence = None
    for sentence in re.split(r"[。；;\n]", text):
        if any(term in sentence for term in REGISTRATION_TERMS + ["粉丝", "账号", "达人"]):
            account_sentence = sentence.strip()[:240]
            break
    publish_sentence = None
    for sentence in re.split(r"[。；;\n]", text):
        if any(term in sentence for term in CREATOR_ACTION_TERMS):
            publish_sentence = sentence.strip()[:240]
            break
    material_sentence = None
    for sentence in re.split(r"[。；;\n]", text):
        if any(term in sentence for term in ["素材", "模板", "脚本", "BGM", "下载"]):
            material_sentence = sentence.strip()[:240]
            break
    host = urlparse(source_url).netloc.lower()
    publisher_type = "平台" if source_reliability_for_url(source_url, configured_level=configured_reliability) == "A" else None
    return validate_candidate(
        {
            "candidate_id": campaign_candidate_id(source_url, title, host),
            "source_id": source_id,
            "source_platform": source_platform,
            "content_platform": content_platform or source_platform,
            "publisher_name": host or source_platform,
            "publisher_type": publisher_type,
            "campaign_name": (title or reward_sentence or source_url)[:160],
            "campaign_type": "内容推广活动",
            "source_url": source_url,
            "registration_url": source_url if any(term in text for term in REGISTRATION_TERMS) else None,
            "reward_model": reward_sentence,
            "account_requirements": account_sentence,
            "publish_requirements": publish_sentence,
            "material_requirements": material_sentence,
            "deadline": deadline,
            "source_reliability": configured_reliability,
            "raw_text": text[:5000],
            "raw_snapshot": raw_snapshot,
            **reward_numbers,
        }
    )


def score_campaign(record: dict[str, Any], account_profile: dict[str, Any] | None = None) -> CampaignScore:
    reasons: list[str] = []
    risk = record.get("risk_level") or "未知"
    reliability = record.get("source_reliability") or "D"
    if risk == "高":
        return CampaignScore(0, "高风险", ["存在高风险信号，不进入推荐。"], None, None, None)

    reward_min = record.get("guaranteed_reward") or record.get("reward_min")
    reward_max = record.get("reward_max")
    reward_model = str(record.get("reward_model") or record.get("reward_description") or "")
    has_settlement = any(term in reward_model for term in ["保底", "按播放量", "阶梯", "CPA", "CPM", "CPS", "结算"]) or not is_missing(reward_min)
    reward_certainty = 1.0 if not is_missing(reward_min) else (0.65 if has_settlement else 0.25)
    reasons.append(f"收益确定性按保底/结算规则评估为 {reward_certainty:.2f}。")

    req_text = str(record.get("account_requirements") or "")
    account_match = 0.7
    if any(term in req_text for term in ["无门槛", "不限", "0粉", "零粉"]):
        account_match = 1.0
    elif any(term in req_text for term in ["万粉", "认证", "机构"]):
        account_match = 0.35
    reasons.append(f"账号匹配度根据门槛文本评估为 {account_match:.2f}。")

    publish_text = str(record.get("publish_requirements") or "")
    difficulty = 0.75
    hours = 2.5
    if any(term in publish_text for term in ["真人出镜", "实拍", "剧情", "复杂剪辑"]):
        difficulty = 0.35
        hours = 8
    elif any(term in publish_text for term in ["原创", "攻略", "剪辑"]):
        difficulty = 0.6
        hours = 4
    reasons.append(f"制作难度折算为 {difficulty:.2f}，预计 {hours:g} 小时。")

    days = remaining_days(record.get("deadline"))
    if days is None:
        time_score = 0.35
        reasons.append("缺少截止时间，剩余时间评分偏低。")
    elif days < 0:
        time_score = 0
        reasons.append("活动已过期。")
    elif days <= 3:
        time_score = 0.35
        reasons.append(f"剩余 {days} 天，时间紧。")
    elif days <= 14:
        time_score = 0.8
        reasons.append(f"剩余 {days} 天，仍可安排制作。")
    else:
        time_score = 1.0
        reasons.append(f"剩余 {days} 天，时间充足。")

    material_score = 1.0 if not is_missing(record.get("material_requirements")) else 0.35
    reasons.append("素材可获得性已按素材字段评估。")
    reliability_score = {"A": 1.0, "B": 0.85, "C": 0.65, "D": 0.35, "E": 0.1}.get(str(reliability), 0.35)
    reasons.append(f"来源可信度等级 {reliability}。")

    score = round(
        100
        * (
            reward_certainty * 0.25
            + account_match * 0.20
            + difficulty * 0.15
            + time_score * 0.15
            + material_score * 0.10
            + reliability_score * 0.15
        ),
        1,
    )
    expected_income = None
    if not is_missing(reward_min):
        expected_income = float(reward_min)
    elif not is_missing(reward_max):
        expected_income = round(float(reward_max) * 0.2, 2)
    expected_hourly = round(expected_income / hours, 2) if expected_income is not None and hours else None
    if reliability in {"D", "E"}:
        recommendation = "观望"
    elif score >= 82:
        recommendation = "强烈推荐"
    elif score >= 68:
        recommendation = "推荐做"
    elif score >= 52:
        recommendation = "可以尝试"
    elif score >= 38:
        recommendation = "观望"
    else:
        recommendation = "不建议"
    if any(is_missing(record.get(field)) for field in ["reward_model", "deadline", "account_requirements"]):
        recommendation = "信息不足" if recommendation in {"可以尝试", "观望", "不建议"} else recommendation
    return CampaignScore(score, recommendation, reasons, expected_income, hours, expected_hourly)


def campaign_record_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    scored = score_campaign(candidate)
    campaign_id = campaign_candidate_id(candidate.get("source_url"), candidate.get("campaign_name"), candidate.get("publisher_name"))
    return {
        **candidate,
        "campaign_id": campaign_id,
        "recommendation": scored.recommendation,
        "score": scored.score,
        "score_reasons": "\n".join(scored.reasons),
        "expected_income": scored.expected_income,
        "estimated_production_hours": scored.estimated_production_hours,
        "expected_hourly_income": scored.expected_hourly_income,
        "status": "有效" if scored.recommendation != "高风险" else "疑似风险",
    }


def candidate_from_task_like(task: Any, source_id: str | None = None, raw_text: str | None = None) -> dict[str, Any]:
    reward_numbers = parse_reward_numbers(getattr(task, "reward_description", None))
    source_url = getattr(task, "source_url", None)
    return validate_candidate(
        {
            "candidate_id": campaign_candidate_id(source_url, getattr(task, "task_name", None), None),
            "source_id": source_id,
            "source_platform": getattr(task, "platform", None),
            "content_platform": getattr(task, "platform", None),
            "publisher_name": getattr(task, "platform", None),
            "publisher_type": "平台",
            "campaign_name": getattr(task, "task_name", None),
            "campaign_type": getattr(task, "task_type", None),
            "source_url": source_url,
            "registration_url": getattr(task, "signup_url", None) or source_url,
            "reward_model": getattr(task, "reward_description", None),
            "account_requirements": getattr(task, "account_requirements", None),
            "publish_requirements": getattr(task, "production_requirements", None),
            "material_requirements": getattr(task, "material_url", None),
            "deadline": getattr(task, "deadline", None),
            "raw_text": raw_text,
            "raw_snapshot": getattr(task, "raw_snapshot", None),
            **reward_numbers,
        }
    )

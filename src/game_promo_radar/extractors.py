from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlparse

from .rules import is_missing

REWARD_KEYWORDS = ["奖励", "现金", "瓜分", "激励", "佣金", "结算", "播放量", "CPA", "CPS", "CPM", "保底", "阶梯奖励", "流量扶持"]
DEADLINE_KEYWORDS = ["截止至", "投稿截止", "报名截止", "活动时间", "任务周期", "截止"]
ENTRY_KEYWORDS = ["粉丝", "实名", "账号", "等级", "达人", "创作者", "机构", "报名", "入驻", "审核", "仅限", "资格"]
MATERIAL_KEYWORDS = ["素材包", "官方素材", "视频素材", "图片素材", "BGM", "音乐", "脚本", "模板", "授权", "下载"]
PRODUCTION_KEYWORDS = ["视频时长", "横屏", "竖屏", "口播", "混剪", "二创", "试玩", "录屏", "攻略", "原创", "真人出镜", "挂载组件"]
RISK_KEYWORDS = ["禁止", "不得", "违规", "侵权", "版权", "授权", "下架", "审核不通过", "不结算", "结算异常", "限制", "黑名单"]
HIGH_RISK_WORDS = ["不结算", "侵权", "违规", "黑名单", "下架"]
MEDIUM_RISK_WORDS = ["禁止", "不得", "限制", "审核", "审核不通过"]
HEAT_WORDS = ["热度", "搜索指数", "趋势", "上升", "热门", "爆款", "流量"]
RANK_WORDS = ["榜单", "排名", "免费榜", "畅销榜", "预约榜", "热门榜", "TapTap评分", "下载量", "预约量"]
AD_WORDS = ["买量", "投放", "广告", "素材量", "巨量", "DataEye", "AppGrowing", "落地页"]
SAMPLE_WORDS = ["点赞", "播放", "评论", "收藏", "转发", "爆款", "样本", "视频链接"]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clean_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", "\n", str(value or ""))
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return _normalize_text(text)


def html_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not match:
        return None
    return clean_text(match.group(1)) or None


def _split_sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[。！？!?；;])|\n+", text)
    result: list[str] = []
    for chunk in chunks:
        clean = _normalize_text(chunk)
        if clean:
            result.append(clean)
    return result


def _keyword_sentences(text: str, keywords: list[str], *, limit: int = 2, max_len: int = 140) -> str | None:
    sentences = _split_sentences(text)
    hits: list[str] = []
    for sentence in sentences:
        if any(word.lower() in sentence.lower() for word in keywords):
            hits.append(sentence[:max_len])
        if len(hits) >= limit:
            break
    if hits:
        return "；".join(hits)
    lower = text.lower()
    for word in keywords:
        idx = lower.find(word.lower())
        if idx >= 0:
            start = max(0, idx - 45)
            end = min(len(text), idx + 95)
            return _normalize_text(text[start:end])
    return None


def _keyword_hits(text: str, keywords: list[str]) -> str | None:
    hits = [word for word in keywords if word.lower() in text.lower()]
    return "、".join(dict.fromkeys(hits)) if hits else None


def _infer_platform(url: str | None, text: str = "") -> str | None:
    if not url:
        return None
    host = urlparse(url).netloc.lower()
    if "taptap" in host:
        return "TapTap"
    if "bilibili" in host:
        return "B站"
    if "douyin" in host or "oceanengine" in host:
        return "抖音"
    if "kuaishou" in host:
        return "快手"
    if "qimai" in host:
        return "七麦数据"
    if "dataeye" in host:
        return "DataEye"
    if "appgrowing" in host:
        return "AppGrowing"
    return None


def _extract_title_name(text: str) -> str | None:
    title_match = re.search(r"(?:标题|title|页面标题)[:：]\s*([^。；\n]{4,80})", text, re.I)
    if title_match:
        return _normalize_text(title_match.group(1))
    first = _split_sentences(text)[0] if _split_sentences(text) else None
    if first and len(first) <= 80:
        return first
    return None


def _extract_game_name(text: str) -> str | None:
    patterns = [
        r"《([^》]{1,30})》",
        r"(?:游戏名|游戏名称|游戏)[:：]\s*([A-Za-z0-9\u4e00-\u9fff：:·\- ]{2,30})",
        r"TapTap\s*[×xX]\s*([A-Za-z0-9\u4e00-\u9fff：:·\- ]{2,30})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return _normalize_text(match.group(1)).strip(" -_")
    return None


def _date_to_iso(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def extract_dates(text: str, *, today: date | None = None) -> list[str]:
    today = today or date.today()
    dates: list[str] = []
    patterns = [
        (r"(20\d{2})[-/\.](\d{1,2})[-/\.](\d{1,2})", True),
        (r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日?", True),
        (r"(?<!\d)(\d{1,2})月\s*(\d{1,2})日?", False),
    ]
    for pattern, has_year in patterns:
        for match in re.finditer(pattern, text):
            if has_year:
                year, month, day = map(int, match.groups())
            else:
                year = today.year
                month, day = map(int, match.groups())
            iso = _date_to_iso(year, month, day)
            if iso and iso not in dates:
                dates.append(iso)
    return dates


def _extract_deadline(text: str) -> str | None:
    sentences = _split_sentences(text)
    for sentence in sentences:
        if any(word in sentence for word in DEADLINE_KEYWORDS):
            found = extract_dates(sentence)
            if found:
                return found[-1]
    found = extract_dates(text)
    return found[-1] if found else None


def _task_status(text: str, deadline: str | None) -> str:
    if any(word in text for word in ["已开奖", "获奖公示", "活动已结束", "已结束", "下架"]):
        return "已结束"
    if deadline:
        return "待确认"
    return "信息不足"


def _risk_level(text: str) -> str:
    if any(word in text for word in HIGH_RISK_WORDS):
        return "高"
    if any(word in text for word in MEDIUM_RISK_WORDS):
        return "中"
    if any(word in text for word in RISK_KEYWORDS):
        return "低"
    return "未知"


def extract_opportunity_fields(text: str, url: str | None = None) -> dict:
    clean = _normalize_text(text)
    deadline = _extract_deadline(clean)
    risk_hits = _keyword_hits(clean, RISK_KEYWORDS)
    return {
        "task_name": _extract_title_name(clean),
        "game_name": _extract_game_name(clean),
        "source_platform": _infer_platform(url, clean),
        "source_url": url,
        "publish_time": extract_dates(clean)[0] if extract_dates(clean) else None,
        "deadline": deadline,
        "reward_summary": _keyword_sentences(clean, REWARD_KEYWORDS),
        "entry_requirements": _keyword_sentences(clean, ENTRY_KEYWORDS),
        "material_requirements": _keyword_sentences(clean, MATERIAL_KEYWORDS),
        "production_requirements": _keyword_sentences(clean, PRODUCTION_KEYWORDS),
        "task_status": _task_status(clean, deadline),
        "raw_text_excerpt": clean[:500] if clean else None,
        "heat_keywords": _keyword_hits(clean, HEAT_WORDS),
        "app_rank_keywords": _keyword_hits(clean, RANK_WORDS),
        "ad_keywords": _keyword_hits(clean, AD_WORDS),
        "sample_video_keywords": _keyword_hits(clean, SAMPLE_WORDS),
        "material_keywords": _keyword_hits(clean, MATERIAL_KEYWORDS),
        "risk_keywords": risk_hits,
        "risk_level": _risk_level(clean),
    }


def has_useful_extraction(fields: dict) -> bool:
    useful = ["task_name", "game_name", "deadline", "reward_summary", "entry_requirements", "material_requirements", "production_requirements"]
    return sum(0 if is_missing(fields.get(field)) else 1 for field in useful) >= 2

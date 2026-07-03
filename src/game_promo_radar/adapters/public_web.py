from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

from game_promo_radar.adapters.base import AdapterResult, SourceAdapter, save_snapshot
from game_promo_radar.models import Task
from game_promo_radar.rules import is_missing


@dataclass
class PublicPageIntel:
    page_title: str | None
    task_name: str | None
    platform: str | None
    game_name: str | None
    reward_description: str | None
    unit_price: float | None
    revenue_share: float | None
    account_requirements: str | None
    start_time: str | None
    deadline: str | None
    material_requirements: str | None
    production_requirements: str | None
    requires_real_person: bool | None
    requires_original_shooting: bool | None
    requires_complex_editing: bool | None
    public_heat_clues: str | None
    competition_clues: str | None


LABELS = {
    "task_name": ("任务名称", "任务名", "活动名称", "活动标题", "推广任务", "活动主题", "征集主题"),
    "platform": ("平台", "发布平台", "推广平台"),
    "game_name": ("游戏名称", "游戏名", "推广游戏", "产品名称", "游戏", "作品名称"),
    "reward_description": (
        "奖励",
        "收益",
        "奖励/收益",
        "任务奖励",
        "活动奖励",
        "投稿奖励",
        "现金奖励",
        "奖金",
        "结算规则",
        "计费方式",
    ),
    "account_requirements": (
        "报名门槛",
        "账号要求",
        "报名要求",
        "参与条件",
        "参与方式",
        "投稿方式",
        "报名方式",
        "达人要求",
    ),
    "start_time": ("开始时间", "活动开始", "报名开始"),
    "deadline": ("截止时间", "报名截止", "活动截止", "截止日期", "结束时间", "活动时间", "投稿时间"),
    "material_requirements": ("素材要求", "素材链接", "素材", "官方素材", "素材包", "素材下载"),
    "production_requirements": (
        "制作要求",
        "视频要求",
        "内容要求",
        "发布要求",
        "创作要求",
        "作品要求",
        "投稿要求",
        "攻略要求",
        "二创要求",
    ),
    "public_heat_clues": ("热度", "播放量", "曝光", "浏览量", "参与人数", "投稿数量"),
    "competition_clues": ("竞争", "投稿人数", "参与门槛", "名额", "排行榜", "赛道"),
}

REWARD_KEYWORDS = ("奖励", "收益", "奖金", "现金", "稿费", "分成", "佣金", "结算", "元", "¥", "￥")
PARTICIPATION_KEYWORDS = ("报名", "参与方式", "投稿方式", "投稿", "发布", "带话题", "参与条件", "达人", "粉丝")
TIME_KEYWORDS = ("活动时间", "投稿时间", "截止", "截至", "报名时间", "开始时间", "结束时间")
MATERIAL_KEYWORDS = ("素材", "素材包", "官方素材", "下载")
PRODUCTION_KEYWORDS = ("视频", "图文", "攻略", "二创", "直播", "内容要求", "创作要求", "作品要求", "发布要求", "剪辑")
HEAT_KEYWORDS = ("播放量", "曝光", "浏览量", "热度", "参与人数", "投稿数量", "预约量")
COMPETITION_KEYWORDS = ("竞争", "投稿人数", "名额", "排行榜", "赛道", "排名", "获奖名额")


def _title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not match:
        return None
    return _clean_value(match.group(1))


def _visible_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", "\n", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|section|article|li|tr|h[1-6]|dd|dt|td|th)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    return text.strip()


def _expanded_text(html: str) -> str:
    text = _visible_text(html)
    meta_values = re.findall(r'<meta[^>]+(?:content|value)=["\']([^"\']+)["\']', html, re.I)
    json_like = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S)
    extra = " ".join(meta_values + json_like)
    extra = unescape(re.sub(r"<[^>]+>", " ", extra))
    extra = re.sub(r"[ \t\r\f\v]+", " ", extra).strip()
    return f"{text}\n{extra}".strip()


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = unescape(re.sub(r"\s+", " ", value)).strip(" ：:，,。；;|-")
    if is_missing(cleaned):
        return None
    return cleaned[:240]


def _extract_labeled_value(text: str, labels: tuple[str, ...]) -> str | None:
    escaped = "|".join(re.escape(label) for label in labels)
    patterns = [
        rf"(?:^|\n)\s*(?:{escaped})\s*[：:]\s*([^\n]+)",
        rf"(?:{escaped})\s*[：:]\s*([^\n。；;]+)",
        rf"(?:^|\n)\s*(?:{escaped})\s*[丨|｜]\s*([^\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return _clean_value(match.group(1))
    return None


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[\n。；;!?！？]", text)
    return [cleaned for part in parts if (cleaned := _clean_value(part))]


def _extract_keyword_value(text: str, keywords: tuple[str, ...], *, require_value_hint: bool = False) -> str | None:
    for sentence in _sentences(text):
        if not any(keyword in sentence for keyword in keywords):
            continue
        if any(term in sentence for term in ("没有", "暂无", "无相关", "未提供", "不含", "无需")):
            continue
        if require_value_hint and not re.search(r"\d|元|¥|￥|%|现金|奖励|奖金|分成|稿费|佣金|素材|视频|图文|攻略|二创|直播|投稿|报名|话题", sentence):
            continue
        return sentence
    return None


def _extract_date(value: str | None) -> str | None:
    if is_missing(value):
        return None
    text = str(value)
    matches = re.findall(r"(2\d{3})[./年-]\s*(\d{1,2})[./月-]\s*(\d{1,2})", text)
    if not matches:
        return None
    year, month, day = matches[-1]
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _extract_start_date(value: str | None) -> str | None:
    if is_missing(value):
        return None
    matches = re.findall(r"(2\d{3})[./年-]\s*(\d{1,2})[./月-]\s*(\d{1,2})", str(value))
    if not matches:
        return None
    year, month, day = matches[0]
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _extract_title_task(title: str | None) -> str | None:
    if is_missing(title):
        return None
    text = str(title)
    if any(term in text for term in ("激励", "投稿", "奖励", "征集", "活动", "发行人", "推广任务", "二创")):
        return _clean_value(re.sub(r"[-_｜|].*$", "", text))
    return None


def _extract_title_game(text: str) -> str | None:
    for pattern in (r"《([^》]{1,40})》", r"「([^」]{1,40})」", r"【([^】]{1,40})】"):
        match = re.search(pattern, text)
        if match:
            return _clean_value(match.group(1))
    return None


def _merge_text(*values: str | None) -> str | None:
    chunks: list[str] = []
    for value in values:
        if not is_missing(value):
            cleaned = _clean_value(str(value))
            if cleaned and cleaned not in chunks:
                chunks.append(cleaned)
    if not chunks:
        return None
    return "；".join(chunks)[:240]


def _platform_hint(platform: str | None, text: str) -> str | None:
    if not is_missing(platform):
        return platform
    if "抖音" in text or "游戏发行人计划" in text:
        return "抖音"
    if "快手" in text or "磁力聚星" in text or "星火计划" in text:
        return "快手"
    if "TapTap" in text:
        return "TapTap"
    if "B站" in text or "哔哩哔哩" in text or "bilibili" in text.lower():
        return "B站"
    return None


def _extract_money(value: str | None) -> float | None:
    if is_missing(value):
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*元", str(value))
    if not match:
        return None
    return float(match.group(1))


def _extract_percent(value: str | None) -> float | None:
    if is_missing(value):
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", str(value))
    if not match:
        return None
    return float(match.group(1))


def _detect_requirement(text: str, positive: tuple[str, ...], negative: tuple[str, ...]) -> bool | None:
    if any(term in text for term in negative):
        return False
    if any(term in text for term in positive):
        return True
    return None


def _extract_keyword_sentence(text: str, keywords: tuple[str, ...]) -> str | None:
    for line in re.split(r"[\n。；;]", text):
        cleaned = _clean_value(line)
        if cleaned and any(keyword in cleaned for keyword in keywords):
            return cleaned
    return None


def parse_public_page(html: str, default_platform: str | None = None, extra_text: str | None = None) -> PublicPageIntel:
    text = _expanded_text(html)
    if not is_missing(extra_text):
        text = f"{text}\n{extra_text}"
    title = _title(html)
    values = {field: _extract_labeled_value(text, labels) for field, labels in LABELS.items()}
    reward = values["reward_description"] or _extract_keyword_value(text, REWARD_KEYWORDS, require_value_hint=True)
    participation = values["account_requirements"] or _extract_keyword_value(text, PARTICIPATION_KEYWORDS, require_value_hint=True)
    time_text = values["deadline"] or _extract_labeled_value(text, ("截止", "截止至", "截至")) or _extract_keyword_value(
        text, TIME_KEYWORDS, require_value_hint=True
    )
    material = values["material_requirements"] or _extract_keyword_value(text, MATERIAL_KEYWORDS, require_value_hint=True)
    production = values["production_requirements"] or _extract_keyword_value(text, PRODUCTION_KEYWORDS, require_value_hint=True)
    task_name = values["task_name"] or _extract_title_task(title)
    game_name = values["game_name"] or _extract_title_game(f"{title or ''}\n{text[:1200]}")
    return PublicPageIntel(
        page_title=title,
        task_name=task_name,
        platform=_platform_hint(values["platform"] or default_platform, text),
        game_name=game_name,
        reward_description=reward,
        unit_price=_extract_money(reward),
        revenue_share=_extract_percent(reward),
        account_requirements=participation,
        start_time=_extract_start_date(values["start_time"] or time_text),
        deadline=_extract_date(time_text),
        material_requirements=material,
        production_requirements=production,
        requires_real_person=_detect_requirement(
            _merge_text(text, production) or text,
            ("真人出镜", "需要出镜", "需出镜", "本人出镜", "真人口播", "口播出镜"),
            ("无需真人出镜", "不需要真人出镜", "无需出镜", "不要求出镜"),
        ),
        requires_original_shooting=_detect_requirement(
            _merge_text(text, production) or text,
            ("原创拍摄", "原创实拍", "需要实拍", "需实拍", "自行拍摄", "原创内容", "原创作品"),
            ("无需原创拍摄", "不需要原创拍摄", "无需实拍", "不要求实拍"),
        ),
        requires_complex_editing=_detect_requirement(
            _merge_text(text, production) or text,
            ("复杂剪辑", "精剪", "多段剪辑", "需要剪辑包装", "需剪辑包装", "包装剪辑"),
            ("无需复杂剪辑", "不需要复杂剪辑", "简单剪辑即可", "无需剪辑"),
        ),
        public_heat_clues=values["public_heat_clues"]
        or _extract_keyword_sentence(text, HEAT_KEYWORDS),
        competition_clues=values["competition_clues"]
        or _extract_keyword_sentence(text, COMPETITION_KEYWORDS),
    )


class PublicPageAdapter(SourceAdapter):
    key = "public"
    name = "公开网页"

    def __init__(
        self,
        platform: str,
        game_name: str,
        task_name: str,
        urls: list[str],
        snapshot_dir: str | Path = "data/snapshots",
    ) -> None:
        self.platform = platform
        self.game_name = game_name
        self.task_name = task_name
        self.urls = urls
        self.snapshot_dir = snapshot_dir

    def collect(self) -> AdapterResult:
        tasks: list[Task] = []
        messages: list[str] = []
        for url in self.urls:
            try:
                req = Request(url, headers={"User-Agent": "game-promo-radar/0.2 personal-local"})
                with urlopen(req, timeout=20) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
                snapshot = save_snapshot(self.snapshot_dir, self.key, html)
                intel = parse_public_page(html, self.platform)
                title = intel.task_name or intel.page_title or self.task_name
                tasks.append(
                    Task(
                        platform=intel.platform or self.platform,
                        game_name=intel.game_name or self.game_name,
                        task_name=title,
                        page_title=intel.page_title,
                        reward_description=intel.reward_description,
                        task_type="普通创作激励",
                        unit_price=intel.unit_price,
                        revenue_share=intel.revenue_share,
                        start_time=intel.start_time,
                        deadline=intel.deadline,
                        account_requirements=intel.account_requirements,
                        material_url=intel.material_requirements,
                        production_requirements=intel.production_requirements,
                        requires_real_person=intel.requires_real_person,
                        requires_original_shooting=intel.requires_original_shooting,
                        requires_complex_editing=intel.requires_complex_editing,
                        public_heat_clues=intel.public_heat_clues,
                        competition_clues=intel.competition_clues,
                        source_url=url,
                        signup_url=url,
                        raw_snapshot=snapshot,
                        confidence=0.7,
                    )
                )
                time.sleep(1)
            except Exception as exc:
                messages.append(f"{url}: {exc}")
        status = "ok" if tasks else "blocked"
        return AdapterResult(tasks, status, "; ".join(messages))

class DouyinGamePublisherAdapter(PublicPageAdapter):
    key = "douyin_game_publisher"
    name = "抖音游戏发行人计划"

    def __init__(self, urls: list[str], snapshot_dir: str | Path = "data/snapshots") -> None:
        super().__init__("抖音", None, "抖音游戏发行人计划公开通告", urls, snapshot_dir)
        self.key = "douyin_game_publisher"


class KuaishouSparkAdapter(PublicPageAdapter):
    key = "kuaishou_spark"
    name = "快手星火计划"

    def __init__(self, urls: list[str], snapshot_dir: str | Path = "data/snapshots") -> None:
        super().__init__("快手", None, "快手星火计划公开通告", urls, snapshot_dir)
        self.key = "kuaishou_spark"

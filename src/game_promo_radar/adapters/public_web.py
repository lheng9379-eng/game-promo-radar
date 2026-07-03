from __future__ import annotations

import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from game_promo_radar.adapters.base import AdapterResult, SourceAdapter, save_snapshot
from game_promo_radar.models import Task

PROMOTION_KEYWORDS = [
    "推广", "任务", "奖励", "激励", "结算", "佣金", "播放量", "投稿", "征集", "挑战赛",
    "创作者", "达人", "星图", "蒲公英", "磁力聚星", "发行人计划",
]
PLATFORM_KEYWORDS = {
    "抖音": ["抖音", "星图", "发行人计划", "巨量"],
    "快手": ["快手", "磁力聚星", "星火"],
    "小红书": ["小红书", "蒲公英", "笔记"],
    "B站": ["B站", "哔哩哔哩", "bilibili"],
    "TapTap": ["TapTap", "taptap"],
    "品牌官网": ["官网", "品牌"],
}
CATEGORY_KEYWORDS = {
    "game": ["游戏", "手游", "小游戏", "发行人计划", "试玩", "预约"],
    "app": ["App", "APP", "应用", "下载", "注册", "工具"],
    "ecommerce": ["电商", "种草", "带货", "商品", "成交", "佣金"],
    "local_life": ["本地生活", "探店", "餐饮", "酒店", "旅游", "团购"],
    "short_drama": ["短剧", "影视", "剧集", "二创"],
    "brand": ["品牌", "挑战赛", "话题", "征集", "达人"],
    "platform_incentive": ["创作者", "激励", "星图", "蒲公英", "磁力聚星"],
}
SETTLEMENT_KEYWORDS = {
    "play_count": ["播放奖励", "播放量", "CPM"],
    "interaction": ["互动奖励", "点赞", "评论", "互动量"],
    "download": ["下载", "注册", "CPA", "激活"],
    "sale_commission": ["成交佣金", "佣金", "返佣", "CPS"],
    "fixed_reward": ["固定奖励", "奖金", "保底", "入围奖励"],
    "traffic_support": ["流量扶持", "流量奖励", "曝光"],
}


@dataclass
class CrawlCandidate:
    task: Task
    confidence: float
    published_at: str | None = None
    duplicate_hint: str | None = None

    def to_record(self) -> dict[str, Any]:
        data = self.task.to_record()
        data["confidence"] = self.confidence
        data["published_at"] = self.published_at
        data["duplicate_hint"] = self.duplicate_hint
        return data


class TextExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self._in_title = False
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = True
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(urljoin(self.base_url, href))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = False
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data).strip()
        if not text or self._skip:
            return
        if self._in_title:
            self.title_parts.append(text)
        self.text_parts.append(text)

    @property
    def title(self) -> str | None:
        title = " ".join(self.title_parts).strip()
        return title or None

    @property
    def text(self) -> str:
        return "\n".join(self.text_parts)


def fetch_public_page(url: str) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": "content-promo-radar/0.3 personal-local"})
    with urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    extracted = extract_page_content(html, url)
    extracted["html"] = html
    return extracted


def extract_page_content(html: str, url: str = "https://example.com") -> dict[str, Any]:
    parser = TextExtractor(url)
    parser.feed(html)
    text = parser.text
    published = extract_published_at(text)
    return {
        "title": parser.title or _fallback_title(html),
        "text": text,
        "links": parser.links,
        "published_at": published,
    }


def extract_published_at(text: str) -> str | None:
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _fallback_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _match_from_keywords(text: str, mapping: dict[str, list[str]], default: str) -> str:
    for value, keywords in mapping.items():
        if any(keyword in text for keyword in keywords):
            return value
    return default


def identify_platform(text: str, default: str = "品牌官网") -> str:
    return _match_from_keywords(text, PLATFORM_KEYWORDS, default)


def identify_category(text: str, default: str = "other") -> str:
    return _match_from_keywords(text, CATEGORY_KEYWORDS, default)


def identify_settlement(text: str, default: str = "unknown") -> str:
    return _match_from_keywords(text, SETTLEMENT_KEYWORDS, default)


def extract_reward_rule(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    reward_terms = ["奖励", "结算", "佣金", "播放量", "下载", "注册", "流量扶持", "奖金"]
    for line in lines:
        if any(term in line for term in reward_terms):
            return line[:300]
    return None


def recognize_promotion_task(
    page: dict[str, Any],
    source_url: str,
    default_platform: str | None = None,
    default_category: str | None = None,
) -> list[CrawlCandidate]:
    title = page.get("title") or "公开网页推广任务"
    text = f"{title}\n{page.get('text') or ''}"
    keyword_hits = [keyword for keyword in PROMOTION_KEYWORDS if keyword in text]
    if not keyword_hits:
        return []
    platform = identify_platform(text, default_platform or "品牌官网")
    category = identify_category(text, default_category or "other")
    settlement = identify_settlement(text)
    reward_rule = extract_reward_rule(text)
    confidence = min(0.95, 0.35 + 0.08 * len(keyword_hits))
    if settlement != "unknown":
        confidence += 0.1
    if reward_rule:
        confidence += 0.1
    confidence = round(min(confidence, 0.98), 2)
    task = Task(
        platform=platform,
        game_name=title,
        task_name=title,
        source_url=source_url,
        task_category=category,
        settlement_type=settlement,
        reward_rule_text=reward_rule,
        is_game_related=category == "game",
        signup_url=source_url,
        confidence=confidence,
    )
    return [CrawlCandidate(task, confidence, page.get("published_at"))]


def collect_public_web_candidates(
    url: str,
    default_platform: str | None = None,
    default_category: str | None = None,
) -> tuple[list[CrawlCandidate], str | None]:
    try:
        page = fetch_public_page(url)
        return recognize_promotion_task(page, url, default_platform, default_category), None
    except Exception as exc:
        return [], str(exc)


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
        task_category: str = "other",
        settlement_type: str = "unknown",
        content_form: str = "short_video",
        is_game_related: bool = False,
    ) -> None:
        self.platform = platform
        self.game_name = game_name
        self.task_name = task_name
        self.urls = urls
        self.snapshot_dir = snapshot_dir
        self.task_category = task_category
        self.settlement_type = settlement_type
        self.content_form = content_form
        self.is_game_related = is_game_related

    def collect(self) -> AdapterResult:
        tasks: list[Task] = []
        messages: list[str] = []
        for url in self.urls:
            try:
                req = Request(url, headers={"User-Agent": "game-promo-radar/0.2 personal-local"})
                with urlopen(req, timeout=20) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
                snapshot = save_snapshot(self.snapshot_dir, self.key, html)
                title = self._title(html) or self.task_name
                tasks.append(
                    Task(
                        platform=self.platform,
                        game_name=self.game_name,
                        task_name=title,
                        task_type="普通创作激励",
                        task_category=self.task_category,
                        settlement_type=self.settlement_type,
                        content_form=self.content_form,
                        is_game_related=self.is_game_related,
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

    @staticmethod
    def _title(html: str) -> str | None:
        return _fallback_title(html)


class DouyinGamePublisherAdapter(PublicPageAdapter):
    key = "douyin_game_publisher"
    name = "抖音游戏发行人计划"

    def __init__(self, urls: list[str], snapshot_dir: str | Path = "data/snapshots") -> None:
        super().__init__(
            "抖音",
            "待确认",
            "抖音游戏发行人计划公开通告",
            urls,
            snapshot_dir,
            task_category="game",
            settlement_type="unknown",
            is_game_related=True,
        )
        self.key = "douyin_game_publisher"


class KuaishouSparkAdapter(PublicPageAdapter):
    key = "kuaishou_spark"
    name = "快手星火计划"

    def __init__(self, urls: list[str], snapshot_dir: str | Path = "data/snapshots") -> None:
        super().__init__(
            "快手",
            "待确认",
            "快手星火计划公开通告",
            urls,
            snapshot_dir,
            task_category="game",
            settlement_type="traffic_support",
            is_game_related=True,
        )
        self.key = "kuaishou_spark"

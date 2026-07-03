from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from html import unescape
import json
from pathlib import Path
import re
import time
from shutil import which
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .adapters.base import save_snapshot
from .adapters.public_web import parse_public_page
from .db import RadarDB
from .models import Task, normalize_source_url
from .rules import is_missing, lifecycle_status

DEFAULT_SEARCH_QUERIES = [
    "site:bilibili.com/blackboard 游戏 激励 活动 投稿 奖励",
    "site:taptap.cn/moment 创作者激励 投稿 奖励 游戏",
    "site:taptap.cn/activity 游戏 创作者 激励",
    "site:gamepublisher.cn 任务 奖励 投稿",
    "site:kuaishou.com 游戏 推广 任务 激励",
    "游戏 创作者激励",
    "游戏 投稿奖励",
    "游戏 二创活动",
    "游戏 攻略征集",
]

DEFAULT_PUBLIC_SOURCES = [
    ("douyin_game_publisher", "抖音", "https://www.gamepublisher.cn/"),
    (
        "douyin_game_publisher_docs",
        "抖音",
        "https://developer.open-douyin.com/docs/resource/zh-CN/mini-game/operation1/advertiser/pub/introduction",
    ),
    ("kuaishou_juxing", "快手", "https://k.kuaishou.com/"),
    ("kuaishou_spark", "快手", "https://open.kuaishou.com/docs/operate/reviewSpecification/sparkProject/sparkProject.html"),
    ("taptap_creator", "TapTap", "https://www.taptap.cn/"),
    ("bilibili_blackboard", "B站", "https://www.bilibili.com/blackboard/activity-list.html"),
]

DEFAULT_DETAIL_SEEDS = [
    ("seed_taptap_818155807949458862", "TapTap", "https://www.taptap.cn/moment/818155807949458862"),
    ("seed_taptap_812035819974954959", "TapTap", "https://www.taptap.cn/moment/812035819974954959"),
    ("seed_bilibili_opus_1208852477871390755", "B站", "https://www.bilibili.com/opus/1208852477871390755"),
    ("seed_taptap_801858058182459739", "TapTap", "https://www.taptap.cn/moment/801858058182459739"),
    ("seed_taptap_infinitynikki_26", "TapTap", "https://www.taptap.cn/moment/809013787729330483"),
    ("seed_taptap_infinitynikki_25", "TapTap", "https://www.taptap.cn/moment/796356066727165982"),
    ("seed_taptap_infinitynikki_24", "TapTap", "https://www.taptap.cn/moment/786187752067564616"),
    ("seed_taptap_infinitynikki_22", "TapTap", "https://www.taptap.cn/moment/765905497982239379"),
    ("seed_taptap_infinitynikki_public", "TapTap", "https://www.taptap.cn/moment/612982708468974404"),
    ("seed_taptap_wutheringwaves_33", "TapTap", "https://www.taptap.cn/moment/798507701024851113"),
    ("seed_taptap_wutheringwaves_32", "TapTap", "https://www.taptap.cn/moment/783726689258571501"),
    ("seed_taptap_supernatural_creator", "TapTap", "https://www.taptap.cn/moment/697454475593384168"),
    ("seed_taptap_trickcal_creator", "TapTap", "https://www.taptap.cn/moment/750031017460371440"),
    ("seed_taptap_painter_creator", "TapTap", "https://www.taptap.cn/moment/765699439045116145"),
]

DEFAULT_CURRENT_DETAIL_SEEDS = [
    ("current_taptap_818155807949458862", "TapTap", "https://www.taptap.cn/moment/818155807949458862"),
    ("current_taptap_812035819974954959", "TapTap", "https://www.taptap.cn/moment/812035819974954959"),
    ("current_bilibili_opus_1208852477871390755", "B站", "https://www.bilibili.com/opus/1208852477871390755"),
]

POSITIVE_TERMS = (
    "游戏推广",
    "推广任务",
    "创作者激励",
    "创作激励",
    "投稿奖励",
    "二创激励",
    "二创活动",
    "发行人计划",
    "游戏发行人",
    "达人任务",
    "激励活动",
    "征稿",
    "攻略征集",
    "活动规则",
    "奖金",
    "分成",
    "activity",
    "campaign",
    "event",
    "notice",
    "news",
    "moment",
    "blackboard",
    "poster",
    "creator",
    "incentive",
    "reward",
)

GAME_TERMS = ("游戏", "手游", "新游", "TapTap", "B站", "哔哩哔哩", "快手", "抖音")

NEGATIVE_TERMS = (
    "招聘",
    "论文",
    "网盘",
    "破解",
    "私信",
    "后台",
    "登录",
    "代运营",
    "刷量",
    "外挂",
    "客服",
    "下载页",
    "download",
)

HIGH_VALUE_TERMS = (
    "奖励",
    "现金",
    "奖金",
    "收益",
    "激励",
    "稿费",
    "分成",
    "佣金",
    "投稿",
    "活动时间",
    "截止",
    "征集",
    "二创",
)

EXPIRED_TITLE_TERMS = ("已开奖", "获奖公示", "获奖名单", "公示期", "活动已结束", "已结束", "往期")
ACTIVE_PRIORITY_TERMS = ("2026", "最新", "开启", "招募", "征集", "本期", "长期", "活动时间")

SIMILAR_DETAIL_TERMS = (
    "创作激励",
    "激励活动",
    "投稿奖励",
    "攻略征集",
    "二创",
    "版本激励",
    "征集活动",
    "创作者激励",
    "活动规则",
)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""


@dataclass
class OnlineCollectResult:
    tasks: list[Task] = field(default_factory=list)
    new_count: int = 0
    updated_count: int = 0
    new_keys: list[str] = field(default_factory=list)
    updated_keys: list[str] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    failures: list[str] = field(default_factory=list)
    entry_page_count: int = 0
    candidate_count: int = 0
    filtered_count: int = 0
    written_count: int = 0
    quality: dict = field(default_factory=dict)


@dataclass
class CandidateLink:
    url: str
    text: str
    score: int
    platform: str | None = None
    source_url: str | None = None


DETAIL_FIELD_GROUPS = {
    "reward": ("reward_description", "unit_price", "revenue_share"),
    "participation": ("account_requirements",),
    "time": ("deadline",),
    "production": ("material_requirements", "production_requirements"),
    "name": ("task_name", "game_name", "page_title"),
    "rules": ("public_heat_clues", "competition_clues"),
}

SUBSTANTIVE_DETAIL_GROUPS = {"reward", "participation", "time", "production"}

ENTRY_PATHS = (
    "/",
    "/index",
    "/home",
    "/docs",
    "/help",
    "/login",
    "/activity-list",
)

DETAIL_PATH_TERMS = (
    "activity",
    "blackboard/activity",
    "blackboard",
    "moment",
    "news",
    "notice",
    "creator",
    "community",
    "campaign",
    "event",
    "task",
    "article",
    "poster",
    "incentive",
    "reward",
)


def _is_entry_path(path: str) -> bool:
    return path in ENTRY_PATHS or path.endswith("/activity-list") or path.startswith(("/docs/", "/help/", "/login/", "/school/course"))


def is_relevant_result(result: SearchResult) -> bool:
    text = f"{result.title} {result.url} {result.snippet}"
    if any(term.lower() in text.lower() for term in NEGATIVE_TERMS):
        return False
    has_positive = any(term.lower() in text.lower() for term in POSITIVE_TERMS)
    has_game_context = any(term.lower() in text.lower() for term in GAME_TERMS)
    return has_positive and has_game_context


def candidate_score(url: str, text: str = "") -> int:
    combined = f"{url} {text}".lower()
    score = 0
    for term in POSITIVE_TERMS:
        if term.lower() in combined:
            score += 3
    for term in GAME_TERMS:
        if term.lower() in combined:
            score += 1
    for term in DETAIL_PATH_TERMS:
        if term.lower() in combined:
            score += 2
    if "bilibili.com/blackboard/activity" in combined:
        score += 6
    if "taptap.cn/moment" in combined or "taptap.cn/activity" in combined:
        score += 6
    if "taptap.cn/moment" in combined and any(term.lower() in combined for term in SIMILAR_DETAIL_TERMS):
        score += 8
    if any(term.lower() in combined for term in NEGATIVE_TERMS):
        score -= 8
    return score


def is_entry_page(url: str, html: str | None = None) -> bool:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/").lower() or "/"
    if _is_entry_path(path):
        return True
    if html:
        intel = parse_public_page(html, infer_platform(url))
        return not is_detail_page(intel, url)
    return False


def _field_hit_count(intel, html: str = "") -> int:
    groups = 0
    for fields in DETAIL_FIELD_GROUPS.values():
        if any(not is_missing(getattr(intel, field, None)) for field in fields):
            groups += 1
    text = _clean_html_text(html)
    if any(term in text for term in ("活动规则", "官方公告", "参与方式", "投稿方式", "报名方式")):
        groups += 1
    return groups


def _hit_groups(intel, html: str = "") -> set[str]:
    groups: set[str] = set()
    for group, fields in DETAIL_FIELD_GROUPS.items():
        if any(not is_missing(getattr(intel, field, None)) for field in fields):
            groups.add(group)
    text = _clean_html_text(html)
    if any(term in text for term in ("活动规则", "官方公告", "参与方式", "投稿方式", "报名方式")):
        groups.add("rules")
    return groups


def is_high_value_pending(task_or_intel, html: str = "") -> bool:
    fields = [
        getattr(task_or_intel, "reward_description", None) if not isinstance(task_or_intel, dict) else task_or_intel.get("reward_description"),
        getattr(task_or_intel, "account_requirements", None) if not isinstance(task_or_intel, dict) else task_or_intel.get("account_requirements"),
        getattr(task_or_intel, "deadline", None) if not isinstance(task_or_intel, dict) else task_or_intel.get("deadline"),
        getattr(task_or_intel, "production_requirements", None) if not isinstance(task_or_intel, dict) else task_or_intel.get("production_requirements"),
        getattr(task_or_intel, "public_heat_clues", None) if not isinstance(task_or_intel, dict) else task_or_intel.get("public_heat_clues"),
        getattr(task_or_intel, "task_name", None) if not isinstance(task_or_intel, dict) else task_or_intel.get("task_name"),
        html,
    ]
    text = " ".join(str(value) for value in fields if not is_missing(value))
    return any(term in text for term in HIGH_VALUE_TERMS)


def has_expired_clue(html: str, title: str | None = None) -> bool:
    text = f"{title or ''} {_clean_html_text(html)}"
    return any(term in text for term in EXPIRED_TITLE_TERMS)


def is_current_or_unknown(intel, html: str = "", *, today=None) -> bool:
    if has_expired_clue(html, getattr(intel, "page_title", None)):
        return False
    return lifecycle_status(getattr(intel, "start_time", None), getattr(intel, "deadline", None), today=today) != "已截止"


def is_detail_page(intel, url: str, html: str = "") -> bool:
    if is_entry_page(url) and not html:
        return False
    groups = _hit_groups(intel, html)
    if len(groups) < 2:
        return False
    path = urlparse(url).path.rstrip("/").lower() or "/"
    if _is_entry_path(path):
        substantive = groups & SUBSTANTIVE_DETAIL_GROUPS
        return "time" in groups and "name" in groups and len(substantive) >= 2
    return bool(groups & SUBSTANTIVE_DETAIL_GROUPS)


def _clean_html_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_bilibili_activity_links(html: str) -> list[str]:
    links = set()
    patterns = [
        r"https?://(?:www\.)?bilibili\.com/blackboard/activity[^\"'\s<>\\]+",
        r"//(?:www\.)?bilibili\.com/blackboard/activity[^\"'\s<>\\]+",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, html, re.I):
            url = match if match.startswith("http") else "https:" + match
            links.add(unescape(url).rstrip(".,);，。"))
    return sorted(links)


def extract_image_urls(base_url: str, html: str, max_images: int = 8) -> list[str]:
    urls: dict[str, None] = {}
    patterns = [
        r'<img[^>]+(?:src|data-src|data-original)=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'["\'](https?://[^"\']+\.(?:png|jpg|jpeg|webp|gif)(?:\?[^"\']*)?)["\']',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, html, re.I | re.S):
            for item in str(match).split(","):
                candidate = item.strip().split(" ")[0]
                if not candidate or candidate.startswith("data:"):
                    continue
                url = _normalize_search_url(urljoin(base_url, candidate))
                if not url:
                    continue
                lowered = url.lower()
                if any(term in lowered for term in ("logo", "avatar", "icon", "emoji", "qrcode")):
                    continue
                urls[normalize_source_url(url)] = None
                if len(urls) >= max_images:
                    return list(urls.keys())
    return list(urls.keys())


def save_page_images(image_urls: list[str], snapshot_dir: str | Path, page_url: str) -> list[str]:
    if not image_urls:
        return []
    image_dir = Path(snapshot_dir) / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    manifest = {
        "page_url": page_url,
        "image_urls": image_urls,
        "saved": saved,
    }
    for url in image_urls:
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            suffix = ".img"
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        target = image_dir / f"{digest}{suffix}"
        try:
            req = Request(url, headers={"User-Agent": "game-promo-radar/0.4 image-snapshot"})
            with urlopen(req, timeout=20) as resp:
                target.write_bytes(resp.read())
            saved.append(str(target))
        except Exception:
            saved.append(url)
    manifest_path = image_dir / f"manifest-{hashlib.sha1(page_url.encode('utf-8')).hexdigest()[:16]}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    saved.append(str(manifest_path))
    return saved


def ocr_images(image_paths: list[str]) -> tuple[str | None, str]:
    if not image_paths:
        return None, "无图片"
    if not which("tesseract"):
        return None, "图片待识别"
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return None, "图片待识别"
    texts: list[str] = []
    for item in image_paths:
        path = Path(item)
        if not path.exists() or path.suffix.lower() == ".json":
            continue
        try:
            text = pytesseract.image_to_string(Image.open(path), lang="chi_sim+eng")
            cleaned = _clean_html_text(text)
            if cleaned:
                texts.append(cleaned)
        except Exception:
            continue
    if not texts:
        return None, "图片待识别"
    return "\n".join(texts)[:4000], "OCR完成"


def _normalize_search_url(url: str) -> str | None:
    url = unescape(url)
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if parsed.path.startswith("/l/") and parsed.query:
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        if target:
            return unquote(target)
    if parsed.scheme in {"http", "https"}:
        return url
    return None


def parse_search_results(html: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        url = _normalize_search_url(match.group(1))
        title = _clean_html_text(match.group(2))
        if not url or not title:
            continue
        if any(existing.url == url for existing in results):
            continue
        results.append(SearchResult(title=title, url=url))
    return results


def extract_candidate_links(base_url: str, html: str, min_score: int = 4) -> list[CandidateLink]:
    candidates: dict[str, CandidateLink] = {}
    for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        href = match.group(1)
        text = _clean_html_text(match.group(2))
        url = _normalize_search_url(urljoin(base_url, href))
        if not url:
            continue
        normalized = normalize_source_url(url)
        score = candidate_score(normalized, text)
        if score < min_score:
            continue
        if normalized not in candidates or score > candidates[normalized].score:
            candidates[normalized] = CandidateLink(
                url=normalized,
                text=text,
                score=score,
                platform=infer_platform(normalized),
                source_url=base_url,
            )
    return sorted(candidates.values(), key=lambda item: item.score, reverse=True)


def extract_similar_detail_links(base_url: str, html: str, min_score: int = 5) -> list[CandidateLink]:
    links = extract_candidate_links(base_url, html, min_score=min_score)
    filtered: list[CandidateLink] = []
    for item in links:
        combined = f"{item.url} {item.text}"
        if "taptap.cn/moment" not in item.url and "taptap.cn/activity" not in item.url:
            continue
        if any(term in combined for term in SIMILAR_DETAIL_TERMS):
            filtered.append(item)
    return filtered


def search_public_web(query: str, max_results: int = 8) -> list[SearchResult]:
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    req = Request(url, headers={"User-Agent": "game-promo-radar/0.3 public-search"})
    with urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    return [result for result in parse_search_results(html) if is_relevant_result(result)][:max_results]


def infer_platform(url: str, fallback: str | None = None) -> str | None:
    host = urlparse(url).netloc.lower()
    if "douyin" in host or "gamepublisher" in host:
        return "抖音"
    if "kuaishou" in host:
        return "快手"
    if "taptap" in host:
        return "TapTap"
    if "bilibili" in host:
        return "B站"
    return fallback


def fetch_public_html(url: str) -> str:
    req = Request(url, headers={"User-Agent": "game-promo-radar/0.3 public-collect"})
    with urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _value_keywords(text: str) -> str | None:
    hits = [term for term in HIGH_VALUE_TERMS if term in text]
    return "、".join(dict.fromkeys(hits)) or None


def task_from_public_html(url: str, html: str, snapshot_dir: str | Path, fallback_platform: str | None = None) -> Task:
    snapshot = save_snapshot(snapshot_dir, "online_public", html)
    platform = infer_platform(url, fallback_platform)
    image_urls = extract_image_urls(url, html)
    image_paths = save_page_images(image_urls, snapshot_dir, url)
    ocr_text, ocr_status = ocr_images(image_paths)
    intel = parse_public_page(html, platform, extra_text=ocr_text if ocr_status == "OCR完成" else None)
    candidates = extract_candidate_links(url, html)
    bilibili_links = [CandidateLink(link, "B站活动链接", 99, "B站", url) for link in extract_bilibili_activity_links(html)]
    candidate_links = [item.url for item in bilibili_links + candidates[:10]]
    task_name = intel.task_name or intel.page_title or "公开网页推广情报"
    return Task(
        platform=intel.platform or platform or "公开网页",
        game_name=intel.game_name,
        task_name=task_name,
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
        candidate_links="\n".join(dict.fromkeys(candidate_links)) or None,
        image_paths="\n".join(image_paths) or None,
        ocr_text=ocr_text,
        ocr_status=ocr_status if image_paths else None,
        value_keywords=_value_keywords(_clean_html_text(html) + "\n" + (ocr_text or "")),
        source_url=url,
        signup_url=url,
        raw_snapshot=snapshot,
        confidence=0.65,
    )


def _resolve_snapshot_path(value: str | None, root: str | Path = ".") -> Path | None:
    if is_missing(value):
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    return Path(root) / path


def reparse_saved_snapshots(db: RadarDB, project_root: str | Path = ".") -> OnlineCollectResult:
    result = OnlineCollectResult()
    rows = db.df("tasks")
    if rows.empty:
        result.quality = quality_summary(db)
        return result
    root = Path(project_root)
    for row in rows.to_dict("records"):
        snapshot_path = _resolve_snapshot_path(row.get("raw_snapshot"), root)
        if not snapshot_path or not snapshot_path.exists():
            result.filtered_count += 1
            continue
        try:
            html = snapshot_path.read_text(encoding="utf-8", errors="ignore")
            platform = row.get("platform") if not is_missing(row.get("platform")) else infer_platform(row.get("source_url", ""))
            source_url = row.get("source_url")
            image_urls = extract_image_urls(source_url, html)
            image_paths = save_page_images(image_urls, root / "data" / "snapshots", source_url)
            ocr_text, ocr_status = ocr_images(image_paths)
            intel = parse_public_page(html, platform, extra_text=ocr_text if ocr_status == "OCR完成" else None)
            if not is_detail_page(intel, source_url, html):
                result.filtered_count += 1
                if is_high_value_pending(intel, html):
                    result.candidate_count += 1
                continue
            task_name = intel.task_name or intel.page_title or row.get("task_name") or "公开网页推广情报"
            task = Task(
                platform=intel.platform or platform or row.get("platform") or "公开网页",
                game_name=intel.game_name,
                task_name=task_name,
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
                candidate_links="\n".join(item.url for item in extract_candidate_links(source_url, html)[:10])
                or "\n".join(extract_bilibili_activity_links(html))
                or None,
                image_paths="\n".join(image_paths) or None,
                ocr_text=ocr_text,
                ocr_status=ocr_status if image_paths else None,
                value_keywords=_value_keywords(_clean_html_text(html) + "\n" + (ocr_text or "")),
                source_url=source_url,
                signup_url=source_url,
                raw_snapshot=row.get("raw_snapshot"),
                confidence=0.7,
            )
            task.task_id = row.get("task_id") if not is_missing(row.get("task_id")) else None
            rec = task.to_record()
            rec["dedupe_key"] = row["dedupe_key"]
            rec["first_seen_at"] = row.get("first_seen_at")
            rec["source_url"] = row.get("source_url")
            rec["raw_snapshot"] = row.get("raw_snapshot")
            db._update_task_record(db._merge_task_record(row, rec, task.last_updated_at))
            result.tasks.append(task)
            result.success_count += 1
            result.updated_count += 1
            result.updated_keys.append(row["dedupe_key"])
            if is_high_value_pending(intel, html):
                result.candidate_count += 1
        except Exception as exc:
            result.failure_count += 1
            result.failures.append(f"{row.get('source_url')}: {exc}")
    result.written_count = result.updated_count
    result.quality = quality_summary(db)
    return result


def quality_summary(db: RadarDB) -> dict:
    tasks = db.df("tasks")
    if tasks.empty:
        return {"field_completeness": 0.0, "platform_completeness": {}}
    fields = ["reward_description", "account_requirements", "deadline", "material_url", "production_requirements"]
    total = len(tasks) * len(fields)
    present = sum(0 if is_missing(row.get(field)) else 1 for row in tasks.to_dict("records") for field in fields)
    by_platform = {}
    for platform, group in tasks.groupby(tasks["platform"].fillna("待确认")):
        platform_total = len(group) * len(fields)
        platform_present = sum(0 if is_missing(row.get(field)) else 1 for row in group.to_dict("records") for field in fields)
        by_platform[str(platform)] = round(platform_present / max(platform_total, 1), 2)
    return {
        "field_completeness": round(present / max(total, 1), 2),
        "platform_completeness": by_platform,
    }


def collect_public_urls(
    db: RadarDB,
    sources: list[tuple[str, str | None, str]],
    snapshot_dir: str | Path = "data/snapshots",
    pause_seconds: float = 1.0,
) -> OnlineCollectResult:
    result = OnlineCollectResult()
    for source_key, platform, url in sources:
        try:
            html = fetch_public_html(url)
            result.entry_page_count += 1
            candidates = extract_candidate_links(url, html)
            candidates.extend(CandidateLink(link, "B站活动链接", 99, "B站", url) for link in extract_bilibili_activity_links(html))
            result.candidate_count += len(candidates)
            pages: list[tuple[str, str, str | None]] = []
            intel = parse_public_page(html, platform)
            if "bilibili.com/video/" in url and not extract_bilibili_activity_links(html):
                result.filtered_count += 1
            elif is_detail_page(intel, url, html):
                pages.append((url, html, platform))
            else:
                result.filtered_count += 1
            for candidate in candidates[:30]:
                try:
                    candidate_html = fetch_public_html(candidate.url)
                    pages.append((candidate.url, candidate_html, candidate.platform or platform))
                    time.sleep(pause_seconds)
                except Exception as exc:
                    result.failure_count += 1
                    result.failures.append(f"{source_key} {candidate.url}: {exc}")
            for page_url, page_html, page_platform in pages:
                page_intel = parse_public_page(page_html, page_platform)
                if not is_detail_page(page_intel, page_url, page_html):
                    result.filtered_count += 1
                    continue
                task = task_from_public_html(page_url, page_html, snapshot_dir, page_platform)
                status = db.upsert_task(task)
                result.tasks.append(task)
                result.success_count += 1
                result.written_count += 1
                if status == "new":
                    result.new_count += 1
                    result.new_keys.append(task.dedupe_key())
                else:
                    result.updated_count += 1
                    result.updated_keys.append(task.dedupe_key())
            time.sleep(pause_seconds)
        except Exception as exc:
            result.failure_count += 1
            result.failures.append(f"{source_key} {url}: {exc}")
    result.quality = quality_summary(db)
    return result


def collect_detail_seed_urls(
    db: RadarDB,
    seeds: list[tuple[str, str | None, str]] | None = None,
    snapshot_dir: str | Path = "data/snapshots",
    pause_seconds: float = 0.5,
    active_only: bool = False,
) -> OnlineCollectResult:
    result = OnlineCollectResult()
    seeds = seeds or DEFAULT_DETAIL_SEEDS
    for source_key, platform, url in seeds:
        try:
            html = fetch_public_html(url)
            result.entry_page_count += 1
            if "bilibili.com/video/" in url and not extract_bilibili_activity_links(html):
                result.filtered_count += 1
                continue
            intel = parse_public_page(html, platform)
            if active_only and not is_current_or_unknown(intel, html):
                task = task_from_public_html(url, html, snapshot_dir, platform)
                status = db.upsert_task(task)
                result.written_count += 1
                if status == "new":
                    result.new_count += 1
                    result.new_keys.append(task.dedupe_key())
                else:
                    result.updated_count += 1
                    result.updated_keys.append(task.dedupe_key())
                result.filtered_count += 1
                continue
            if not is_detail_page(intel, url, html):
                if "bilibili.com/opus/" in url and is_high_value_pending(intel, html):
                    task = high_value_pending_task_from_html(url, html, snapshot_dir, platform)
                    status = db.upsert_task(task)
                    result.tasks.append(task)
                    result.success_count += 1
                    result.written_count += 1
                    if status == "new":
                        result.new_count += 1
                        result.new_keys.append(task.dedupe_key())
                    else:
                        result.updated_count += 1
                        result.updated_keys.append(task.dedupe_key())
                    continue
                result.filtered_count += 1
                result.candidate_count += len(extract_candidate_links(url, html, min_score=3))
                continue
            task = task_from_public_html(url, html, snapshot_dir, platform)
            status = db.upsert_task(task)
            result.tasks.append(task)
            result.success_count += 1
            result.written_count += 1
            if status == "new":
                result.new_count += 1
                result.new_keys.append(task.dedupe_key())
            else:
                result.updated_count += 1
                result.updated_keys.append(task.dedupe_key())
            time.sleep(pause_seconds)
        except Exception as exc:
            result.failure_count += 1
            result.failures.append(f"{source_key} {url}: {exc}")
    result.quality = quality_summary(db)
    return result


def high_value_pending_task_from_html(url: str, html: str, snapshot_dir: str | Path, fallback_platform: str | None = None) -> Task:
    snapshot = save_snapshot(snapshot_dir, "online_public", html)
    platform = infer_platform(url, fallback_platform)
    image_urls = extract_image_urls(url, html)
    image_paths = save_page_images(image_urls, snapshot_dir, url)
    ocr_text, ocr_status = ocr_images(image_paths)
    intel = parse_public_page(html, platform, extra_text=ocr_text if ocr_status == "OCR完成" else None)
    candidates = extract_candidate_links(url, html, min_score=3)
    candidates.extend(CandidateLink(link, "B站活动链接", 99, "B站", url) for link in extract_bilibili_activity_links(html))
    title = intel.task_name or intel.page_title or "高价值待确认页面"
    return Task(
        platform=intel.platform or platform or "公开网页",
        game_name=intel.game_name,
        task_name=title,
        page_title=intel.page_title,
        task_type="普通创作激励",
        public_heat_clues=intel.public_heat_clues,
        competition_clues=intel.competition_clues,
        candidate_links="\n".join(dict.fromkeys(item.url for item in candidates[:10])) or None,
        image_paths="\n".join(image_paths) or None,
        ocr_text=ocr_text,
        ocr_status=ocr_status if image_paths else None,
        value_keywords=_value_keywords(_clean_html_text(html) + "\n" + (ocr_text or "")),
        source_url=url,
        signup_url=url,
        raw_snapshot=snapshot,
        confidence=0.35,
    )


def discover_similar_detail_pages(
    db: RadarDB,
    snapshot_dir: str | Path = "data/snapshots",
    project_root: str | Path = ".",
    max_candidates_per_task: int = 12,
    pause_seconds: float = 0.5,
    active_only: bool = True,
) -> OnlineCollectResult:
    result = OnlineCollectResult()
    root = Path(project_root)
    rows = db.df("tasks")
    if rows.empty:
        result.quality = quality_summary(db)
        return result
    existing_urls = {normalize_source_url(url) for url in rows["source_url"].dropna().astype(str).tolist()}
    seen = set(existing_urls)
    queue: list[tuple[str, str | None, str]] = []
    for row in rows.to_dict("records"):
        url = str(row.get("source_url") or "")
        if "taptap.cn/moment" not in url and "taptap.cn/activity" not in url:
            continue
        snapshot_path = _resolve_snapshot_path(row.get("raw_snapshot"), root)
        if not snapshot_path or not snapshot_path.exists():
            result.filtered_count += 1
            continue
        html = snapshot_path.read_text(encoding="utf-8", errors="ignore")
        candidates = extract_similar_detail_links(url, html)
        candidates = sorted(
            candidates,
            key=lambda item: (
                0 if any(term in f"{item.text} {item.url}" for term in EXPIRED_TITLE_TERMS) else 1,
                1 if any(term in f"{item.text} {item.url}" for term in ACTIVE_PRIORITY_TERMS) else 0,
                item.score,
            ),
            reverse=True,
        )
        result.candidate_count += len(candidates)
        for candidate in candidates[:max_candidates_per_task]:
            normalized = normalize_source_url(candidate.url)
            if normalized in seen:
                continue
            seen.add(normalized)
            queue.append((f"similar:{row.get('dedupe_key')}", candidate.platform or "TapTap", normalized))
    for source_key, platform, url in queue:
        try:
            html = fetch_public_html(url)
            intel = parse_public_page(html, platform)
            if active_only and not is_current_or_unknown(intel, html):
                result.filtered_count += 1
                continue
            if not is_detail_page(intel, url, html):
                result.filtered_count += 1
                continue
            task = task_from_public_html(url, html, snapshot_dir, platform)
            status = db.upsert_task(task)
            result.tasks.append(task)
            result.success_count += 1
            result.written_count += 1
            if status == "new":
                result.new_count += 1
                result.new_keys.append(task.dedupe_key())
            else:
                result.updated_count += 1
                result.updated_keys.append(task.dedupe_key())
            time.sleep(pause_seconds)
        except Exception as exc:
            result.failure_count += 1
            result.failures.append(f"{source_key} {url}: {exc}")
    result.quality = quality_summary(db)
    return result


def rediscover_details_from_existing_tasks(
    db: RadarDB,
    snapshot_dir: str | Path = "data/snapshots",
    project_root: str | Path = ".",
    max_candidates_per_task: int = 8,
    pause_seconds: float = 0.5,
) -> OnlineCollectResult:
    result = OnlineCollectResult()
    root = Path(project_root)
    rows = db.df("tasks")
    if rows.empty:
        result.quality = quality_summary(db)
        return result
    seen: set[str] = set()
    queue: list[tuple[str, str | None, str]] = []
    for row in rows.to_dict("records"):
        snapshot_path = _resolve_snapshot_path(row.get("raw_snapshot"), root)
        if not snapshot_path or not snapshot_path.exists():
            result.filtered_count += 1
            continue
        html = snapshot_path.read_text(encoding="utf-8", errors="ignore")
        source_url = row.get("source_url")
        platform = row.get("platform") if not is_missing(row.get("platform")) else infer_platform(source_url or "")
        intel = parse_public_page(html, platform)
        if not is_high_value_pending(intel, html):
            result.filtered_count += 1
            continue
        candidates = extract_candidate_links(source_url, html, min_score=3)
        candidates.extend(CandidateLink(link, "B站活动链接", 99, "B站", source_url) for link in extract_bilibili_activity_links(html))
        result.candidate_count += len(candidates)
        for candidate in sorted(candidates, key=lambda item: item.score, reverse=True)[:max_candidates_per_task]:
            normalized = normalize_source_url(candidate.url)
            if normalized in seen:
                continue
            seen.add(normalized)
            queue.append((f"rediscover:{row.get('dedupe_key')}", candidate.platform or platform, normalized))
    for source_key, platform, url in queue:
        try:
            html = fetch_public_html(url)
            if "bilibili.com/video/" in url:
                activity_links = extract_bilibili_activity_links(html)
                if not activity_links:
                    result.filtered_count += 1
                    continue
                for link in activity_links:
                    if normalize_source_url(link) not in seen:
                        queue.append((source_key, "B站", normalize_source_url(link)))
                result.filtered_count += 1
                continue
            intel = parse_public_page(html, platform)
            if not is_detail_page(intel, url, html):
                result.filtered_count += 1
                continue
            task = task_from_public_html(url, html, snapshot_dir, platform)
            status = db.upsert_task(task)
            result.tasks.append(task)
            result.success_count += 1
            result.written_count += 1
            if status == "new":
                result.new_count += 1
                result.new_keys.append(task.dedupe_key())
            else:
                result.updated_count += 1
                result.updated_keys.append(task.dedupe_key())
            time.sleep(pause_seconds)
        except Exception as exc:
            result.failure_count += 1
            result.failures.append(f"{source_key} {url}: {exc}")
    result.quality = quality_summary(db)
    return result


def collect_from_search(
    db: RadarDB,
    queries: list[str] | None = None,
    snapshot_dir: str | Path = "data/snapshots",
    max_results_per_query: int = 5,
) -> OnlineCollectResult:
    queries = queries or DEFAULT_SEARCH_QUERIES
    candidates: dict[str, tuple[str, str | None, str]] = {}
    failures: list[str] = []
    for query in queries:
        try:
            for item in search_public_web(query, max_results_per_query):
                candidates[normalize_source_url(item.url)] = (f"search:{query}", infer_platform(item.url), normalize_source_url(item.url))
            time.sleep(1)
        except Exception as exc:
            failures.append(f"search:{query}: {exc}")
    result = collect_public_urls(db, list(candidates.values()), snapshot_dir)
    result.failure_count += len(failures)
    result.failures = failures + result.failures
    result.quality = quality_summary(db)
    return result


def collect_online_public(
    db: RadarDB,
    snapshot_dir: str | Path = "data/snapshots",
    include_search: bool = True,
) -> OnlineCollectResult:
    result = collect_public_urls(db, DEFAULT_PUBLIC_SOURCES, snapshot_dir)
    if include_search:
        search_result = collect_from_search(db, DEFAULT_SEARCH_QUERIES, snapshot_dir)
        result.tasks.extend(search_result.tasks)
        result.new_count += search_result.new_count
        result.updated_count += search_result.updated_count
        result.new_keys.extend(search_result.new_keys)
        result.updated_keys.extend(search_result.updated_keys)
        result.success_count += search_result.success_count
        result.failure_count += search_result.failure_count
        result.failures.extend(search_result.failures)
        result.entry_page_count += search_result.entry_page_count
        result.candidate_count += search_result.candidate_count
        result.filtered_count += search_result.filtered_count
        result.written_count += search_result.written_count
    result.quality = quality_summary(db)
    db.log_run(
        "online_public",
        "default_sources_and_keyword_search",
        "ok" if result.success_count else "blocked",
        "; ".join(result.failures),
        result.success_count,
        result.failure_count,
        result.new_count,
        result.updated_count,
    )
    return result

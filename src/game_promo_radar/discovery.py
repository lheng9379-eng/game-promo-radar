from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Iterable
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen

from .adapters.base import save_snapshot
from .campaigns import (
    candidate_from_discovery,
    generate_search_discovery_queries,
    should_save_candidate_loose,
)
from .db import RadarDB
from .models import normalize_source_url, now_iso
from .online_collect import CandidateLink, _clean_html_text, _normalize_search_url, extract_candidate_links, parse_search_results
from .sources import load_platform_sources, sync_sources_to_db


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "game_promo_radar.duckdb"
SNAPSHOT_DIR = ROOT / "data" / "snapshots" / "discovery"
SOURCE_CONFIG = ROOT / "PLATFORM_SOURCE_LIST.yaml"

ACTIVITY_LINK_TERMS = (
    "创作者",
    "投稿",
    "奖励",
    "征集",
    "招募",
    "活动",
    "激励",
    "推广",
    "大赛",
    "现金",
    "瓜分",
    "发行人",
    "达人",
    "博主",
    "campaign",
    "activity",
    "event",
    "creator",
    "reward",
)


@dataclass
class DiscoverySummary:
    mode: str
    source_count: int = 0
    request_success_count: int = 0
    request_failure_count: int = 0
    discovered_link_count: int = 0
    search_result_count: int = 0
    new_candidate_count: int = 0
    updated_candidate_count: int = 0
    risk_candidate_count: int = 0
    filtered_count: int = 0
    filter_reasons: Counter = field(default_factory=Counter)
    failed_sources: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=now_iso)
    finished_at: str | None = None

    def merge(self, other: "DiscoverySummary") -> None:
        self.source_count += other.source_count
        self.request_success_count += other.request_success_count
        self.request_failure_count += other.request_failure_count
        self.discovered_link_count += other.discovered_link_count
        self.search_result_count += other.search_result_count
        self.new_candidate_count += other.new_candidate_count
        self.updated_candidate_count += other.updated_candidate_count
        self.risk_candidate_count += other.risk_candidate_count
        self.filtered_count += other.filtered_count
        self.filter_reasons.update(other.filter_reasons)
        self.failed_sources.extend(other.failed_sources)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "source_count": self.source_count,
            "request_success_count": self.request_success_count,
            "request_failure_count": self.request_failure_count,
            "discovered_link_count": self.discovered_link_count,
            "search_result_count": self.search_result_count,
            "new_candidate_count": self.new_candidate_count,
            "updated_candidate_count": self.updated_candidate_count,
            "risk_candidate_count": self.risk_candidate_count,
            "filtered_count": self.filtered_count,
            "filter_reasons": dict(self.filter_reasons),
            "failed_sources": self.failed_sources,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def fetch_html(url: str, timeout: int = 20) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "game-promo-radar-discovery/1.0 (+local personal research)",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="ignore")


def record_id(url: str, query: str | None = None) -> str:
    basis = f"{normalize_source_url(url)}|{query or ''}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:24]


def _title_from_html(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not match:
        return None
    return _clean_html_text(match.group(1))[:180] or None


def _save_discovery_record(
    db: RadarDB,
    *,
    source_id: str | None,
    method: str,
    url: str,
    title: str | None,
    snippet: str | None,
    query: str | None = None,
    detail_status: str = "not_fetched",
    filter_status: str = "pending",
    filter_reason: str | None = None,
    raw_text: str | None = None,
    raw_snapshot: str | None = None,
    candidate_id: str | None = None,
) -> None:
    db.upsert_discovery_record(
        {
            "record_id": record_id(url, query),
            "source_id": source_id,
            "discovery_method": method,
            "query": query,
            "title": title,
            "snippet": snippet,
            "source_url": normalize_source_url(url),
            "detail_status": detail_status,
            "filter_status": filter_status,
            "filter_reason": filter_reason,
            "raw_text": raw_text,
            "raw_snapshot": raw_snapshot,
            "candidate_id": candidate_id,
        }
    )


def _update_source_discovery(db: RadarDB) -> None:
    records = db.df("discovery_records")
    if records.empty:
        return
    configured = {urlparse(str(row.get("base_url") or "")).netloc.lower() for row in db.df("data_sources").to_dict("records")}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in records.to_dict("records"):
        url = str(row.get("source_url") or "")
        host = urlparse(url).netloc.lower()
        if not host or host in configured:
            continue
        if row.get("filter_status") == "saved_candidate":
            grouped[host].append(row)
    for host, rows in grouped.items():
        if len(rows) < 2:
            continue
        examples = "\n".join(dict.fromkeys(str(row.get("source_url")) for row in rows[:5]))
        db.upsert_source_discovery_candidate(
            {
                "domain": host,
                "source_name_guess": host,
                "last_seen_at": now_iso(),
                "discovered_campaign_count": len(rows),
                "valid_campaign_count": sum(1 for row in rows if row.get("candidate_id")),
                "reliability_guess": "D",
                "example_urls": examples,
                "status": "待确认",
            }
        )


def _persist_candidate(
    db: RadarDB,
    summary: DiscoverySummary,
    *,
    source_id: str | None,
    source_platform: str | None,
    content_platform: str | None,
    source_reliability: str | None,
    url: str,
    title: str | None,
    snippet: str | None,
    detail_text: str | None,
    snapshot_path: str | None,
) -> str | None:
    should_save, reason = should_save_candidate_loose(title, snippet, detail_text)
    if not should_save:
        summary.filtered_count += 1
        summary.filter_reasons[reason] += 1
        _save_discovery_record(
            db,
            source_id=source_id,
            method=summary.mode,
            query=None,
            url=url,
            title=title,
            snippet=snippet,
            detail_status="fetched" if detail_text else "not_fetched",
            filter_status="filtered",
            filter_reason=reason,
            raw_text=detail_text,
            raw_snapshot=snapshot_path,
        )
        return None
    candidate = candidate_from_discovery(
        source_url=normalize_source_url(url),
        title=title,
        snippet=snippet,
        detail_text=detail_text,
        source_id=source_id,
        source_platform=source_platform,
        content_platform=content_platform,
        raw_snapshot=snapshot_path,
        configured_reliability=source_reliability,
    )
    status = db.upsert_campaign_candidate(candidate)
    if status == "new":
        summary.new_candidate_count += 1
    else:
        summary.updated_candidate_count += 1
    if candidate.get("risk_level") == "高" or candidate.get("status") == "疑似风险":
        summary.risk_candidate_count += 1
    _save_discovery_record(
        db,
        source_id=source_id,
        method=summary.mode,
        query=None,
        url=url,
        title=title,
        snippet=snippet,
        detail_status="fetched" if detail_text else "not_fetched",
        filter_status="saved_candidate",
        filter_reason=reason,
        raw_text=detail_text,
        raw_snapshot=snapshot_path,
        candidate_id=candidate.get("candidate_id"),
    )
    return candidate.get("candidate_id")


def search_results(query: str, max_results: int = 8) -> list:
    html = fetch_html(f"https://duckduckgo.com/html/?q={quote_plus(query)}")
    return parse_search_results(html)[:max_results]


def run_search(db: RadarDB, *, max_queries: int = 24, max_results_per_query: int = 5, fetch_details: bool = True) -> DiscoverySummary:
    summary = DiscoverySummary(mode="search")
    queries = generate_search_discovery_queries(max_queries=max_queries)
    summary.source_count = len(queries)
    for query in queries:
        try:
            results = search_results(query, max_results=max_results_per_query)
            summary.request_success_count += 1
            summary.search_result_count += len(results)
        except Exception as exc:
            summary.request_failure_count += 1
            summary.failed_sources.append(f"search:{query}: {exc}")
            summary.filter_reasons["request_failed"] += 1
            continue
        for item in results:
            url = normalize_source_url(item.url)
            summary.discovered_link_count += 1
            detail_text = None
            snapshot_path = None
            title = item.title
            if fetch_details:
                try:
                    html = fetch_html(url, timeout=15)
                    summary.request_success_count += 1
                    snapshot_path = save_snapshot(SNAPSHOT_DIR, "search_detail", html)
                    detail_title = _title_from_html(html)
                    title = detail_title or title
                    detail_text = _clean_html_text(html)[:5000]
                except Exception as exc:
                    summary.request_failure_count += 1
                    summary.failed_sources.append(f"detail:{url}: {exc}")
            should_save, reason = should_save_candidate_loose(title, item.snippet, detail_text)
            if not should_save:
                summary.filtered_count += 1
                summary.filter_reasons[reason] += 1
                _save_discovery_record(
                    db,
                    source_id="search_engine_discovery",
                    method="search",
                    query=query,
                    url=url,
                    title=title,
                    snippet=item.snippet,
                    detail_status="fetched" if detail_text else "not_fetched",
                    filter_status="filtered",
                    filter_reason=reason,
                    raw_text=detail_text,
                    raw_snapshot=snapshot_path,
                )
                continue
            candidate = candidate_from_discovery(
                source_url=url,
                title=title,
                snippet=item.snippet,
                detail_text=detail_text,
                source_id="search_engine_discovery",
                raw_snapshot=snapshot_path,
                configured_reliability="D",
            )
            status = db.upsert_campaign_candidate(candidate)
            if status == "new":
                summary.new_candidate_count += 1
            else:
                summary.updated_candidate_count += 1
            if candidate.get("risk_level") == "高" or candidate.get("status") == "疑似风险":
                summary.risk_candidate_count += 1
            _save_discovery_record(
                db,
                source_id="search_engine_discovery",
                method="search",
                query=query,
                url=url,
                title=title,
                snippet=item.snippet,
                detail_status="fetched" if detail_text else "not_fetched",
                filter_status="saved_candidate",
                filter_reason=reason,
                raw_text=detail_text,
                raw_snapshot=snapshot_path,
                candidate_id=candidate.get("candidate_id"),
            )
        time.sleep(0.3)
    summary.finished_at = now_iso()
    _update_source_discovery(db)
    log_summary(db, summary)
    return summary


def _extract_recent_links(base_url: str, html: str, max_links: int = 12) -> list[CandidateLink]:
    candidates = {item.url: item for item in extract_candidate_links(base_url, html, min_score=2)}
    for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        href, text_html = match.group(1), match.group(2)
        text = _clean_html_text(text_html)
        url = _normalize_search_url(urljoin(base_url, href))
        if not url:
            continue
        combined = f"{url} {text}".lower()
        if not any(term.lower() in combined for term in ACTIVITY_LINK_TERMS):
            continue
        normalized = normalize_source_url(url)
        candidates.setdefault(normalized, CandidateLink(url=normalized, text=text, score=3, source_url=base_url))
    return sorted(candidates.values(), key=lambda item: item.score, reverse=True)[:max_links]


def public_discovery_sources() -> list[dict]:
    sources = load_platform_sources(SOURCE_CONFIG)
    result = []
    for source in sources:
        if source.get("login_required") or not source.get("enabled"):
            continue
        if not str(source.get("base_url") or "").startswith("http"):
            continue
        if source.get("source_id") in {
            "bilibili_creator_activity",
            "taptap_creator",
            "haoyou_kuaibao",
            "kuaishou_creator_activity",
            "xiaohongshu_creator_activity",
            "game_official_sites",
            "brand_official_sites",
        }:
            result.append(source)
    return result[:8]


def run_public_sources(db: RadarDB, *, max_links_per_source: int = 10) -> DiscoverySummary:
    summary = DiscoverySummary(mode="public-sources")
    sources = public_discovery_sources()
    summary.source_count = len(sources)
    for source in sources:
        source_id = source.get("source_id")
        base_url = source.get("base_url")
        try:
            html = fetch_html(base_url)
            summary.request_success_count += 1
        except Exception as exc:
            summary.request_failure_count += 1
            summary.failed_sources.append(f"{source_id}:{base_url}: {exc}")
            summary.filter_reasons["request_failed"] += 1
            continue
        list_snapshot = save_snapshot(SNAPSHOT_DIR, f"{source_id}_list", html)
        title = _title_from_html(html) or source.get("source_name")
        list_text = _clean_html_text(html)[:5000]
        _save_discovery_record(
            db,
            source_id=source_id,
            method="public-sources-list",
            url=base_url,
            title=title,
            snippet=source.get("source_name"),
            detail_status="fetched",
            filter_status="list_page",
            filter_reason="list_page_snapshot",
            raw_text=list_text,
            raw_snapshot=list_snapshot,
        )
        links = _extract_recent_links(base_url, html, max_links=max_links_per_source)
        summary.discovered_link_count += len(links)
        if not links:
            summary.filter_reasons["no_activity_links_on_list"] += 1
        for link in links:
            detail_text = None
            snapshot_path = None
            detail_title = link.text or title
            try:
                detail_html = fetch_html(link.url, timeout=15)
                summary.request_success_count += 1
                snapshot_path = save_snapshot(SNAPSHOT_DIR, f"{source_id}_detail", detail_html)
                detail_title = _title_from_html(detail_html) or detail_title
                detail_text = _clean_html_text(detail_html)[:5000]
            except Exception as exc:
                summary.request_failure_count += 1
                summary.failed_sources.append(f"{source_id}:{link.url}: {exc}")
            _persist_candidate(
                db,
                summary,
                source_id=source_id,
                source_platform=source.get("content_platform"),
                content_platform=source.get("content_platform"),
                source_reliability=source.get("reliability_level"),
                url=link.url,
                title=detail_title,
                snippet=link.text,
                detail_text=detail_text,
                snapshot_path=snapshot_path,
            )
        time.sleep(0.5)
    summary.finished_at = now_iso()
    _update_source_discovery(db)
    log_summary(db, summary)
    return summary


def run_all(db: RadarDB) -> DiscoverySummary:
    summary = DiscoverySummary(mode="all")
    public_summary = run_public_sources(db)
    search_summary = run_search(db)
    summary.merge(public_summary)
    summary.merge(search_summary)
    summary.finished_at = now_iso()
    log_summary(db, summary)
    return summary


def diagnose(db: RadarDB) -> DiscoverySummary:
    summary = DiscoverySummary(mode="diagnose")
    sources = db.df("data_sources")
    candidates = db.df("campaign_candidates")
    records = db.df("discovery_records")
    logs = db.df("crawl_runs")
    summary.source_count = len(sources)
    summary.discovered_link_count = len(records)
    summary.new_candidate_count = len(candidates)
    if not records.empty and "filter_reason" in records.columns:
        summary.filter_reasons.update(records["filter_reason"].dropna().astype(str).tolist())
        summary.filtered_count = int((records["filter_status"] == "filtered").sum())
    if not logs.empty:
        failed = logs[logs["status"] != "ok"]
        summary.request_failure_count = len(failed)
        summary.failed_sources = [
            f"{row.get('source_key')}:{row.get('source_url')}:{row.get('message')}"
            for row in failed.tail(20).to_dict("records")
        ]
    summary.finished_at = now_iso()
    return summary


def log_summary(db: RadarDB, summary: DiscoverySummary) -> None:
    db.log_run(
        f"discovery_{summary.mode}",
        "discovery_runtime",
        "ok" if summary.request_success_count or summary.new_candidate_count or summary.updated_candidate_count else "blocked",
        json.dumps(summary.as_dict(), ensure_ascii=False),
        summary.request_success_count,
        summary.request_failure_count,
        summary.new_candidate_count,
        summary.updated_candidate_count,
    )


def print_summary(summary: DiscoverySummary, campaigns_count: int | None = None) -> None:
    data = summary.as_dict()
    labels = [
        ("扫描来源数", "source_count"),
        ("请求成功数", "request_success_count"),
        ("请求失败数", "request_failure_count"),
        ("发现链接数", "discovered_link_count"),
        ("搜索结果数", "search_result_count"),
        ("新增候选数", "new_candidate_count"),
        ("更新候选数", "updated_candidate_count"),
        ("风险候选数", "risk_candidate_count"),
        ("被过滤数", "filtered_count"),
    ]
    for label, key in labels:
        print(f"{label}: {data[key]}")
    if campaigns_count is not None:
        print(f"正式商机数: {campaigns_count}")
    print("过滤原因数量:")
    if data["filter_reasons"]:
        for reason, count in sorted(data["filter_reasons"].items()):
            print(f"  {reason}: {count}")
    else:
        print("  无")
    print("失败来源列表:")
    if data["failed_sources"]:
        for item in data["failed_sources"][:30]:
            print(f"  {item}")
    else:
        print("  无")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Content campaign discovery runtime")
    parser.add_argument("command", choices=["search", "public-sources", "all", "diagnose"])
    parser.add_argument("--max-queries", type=int, default=24)
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--max-links", type=int, default=10)
    args = parser.parse_args(argv)

    db = RadarDB(DB_PATH)
    sync_sources_to_db(db, SOURCE_CONFIG)
    if args.command == "search":
        summary = run_search(db, max_queries=args.max_queries, max_results_per_query=args.max_results)
    elif args.command == "public-sources":
        summary = run_public_sources(db, max_links_per_source=args.max_links)
    elif args.command == "all":
        summary = run_all(db)
    else:
        summary = diagnose(db)
    print_summary(summary, campaigns_count=len(db.df("campaigns")))
    return 0 if args.command == "diagnose" or summary.request_failure_count == 0 or summary.new_candidate_count or summary.updated_candidate_count else 1


if __name__ == "__main__":
    raise SystemExit(main())

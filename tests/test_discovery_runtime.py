from __future__ import annotations

from pathlib import Path

from game_promo_radar.db import RadarDB
from game_promo_radar.discovery import run_public_sources, run_search
from game_promo_radar.online_collect import SearchResult


def test_search_discovery_saves_incomplete_candidate(tmp_path, monkeypatch):
    db = RadarDB(tmp_path / "radar.duckdb")

    import game_promo_radar.discovery as discovery

    monkeypatch.setattr(
        discovery,
        "search_results",
        lambda query, max_results=8: [
            SearchResult(
                title="测试游戏投稿奖励活动",
                url="https://example-campaign.test/activity/1",
                snippet="创作者发布视频参与投稿，奖励细则待补充",
            )
        ],
    )
    monkeypatch.setattr(
        discovery,
        "fetch_html",
        lambda url, timeout=20: "<html><head><title>测试游戏投稿奖励活动</title></head><body>发布视频参与投稿，奖励待公布。</body></html>",
    )
    monkeypatch.setattr(discovery, "SNAPSHOT_DIR", tmp_path / "snapshots")
    summary = run_search(db, max_queries=1, max_results_per_query=1)
    assert summary.new_candidate_count == 1
    candidates = db.df("campaign_candidates")
    assert len(candidates) == 1
    assert candidates.iloc[0]["status"] in {"待验证", "疑似风险", "验证通过"}
    assert len(db.df("discovery_records")) == 1


def test_search_discovery_records_filter_reasons(tmp_path, monkeypatch):
    db = RadarDB(tmp_path / "radar.duckdb")

    import game_promo_radar.discovery as discovery

    monkeypatch.setattr(
        discovery,
        "search_results",
        lambda query, max_results=8: [SearchResult(title="普通首页", url="https://example.com/", snippet="公司介绍")],
    )
    summary = run_search(db, max_queries=1, max_results_per_query=1, fetch_details=False)
    assert summary.filtered_count == 1
    assert summary.filter_reasons["not_activity_page"] == 1
    assert db.df("campaign_candidates").empty
    assert len(db.df("discovery_records")) == 1


def test_public_source_discovery_extracts_links_and_saves_candidate(tmp_path, monkeypatch):
    db = RadarDB(tmp_path / "radar.duckdb")
    db.upsert_data_source(
        {
            "source_id": "bilibili_creator_activity",
            "source_name": "B站创作中心活动",
            "source_type": "official_account_or_community",
            "content_platform": "B站",
            "base_url": "https://www.bilibili.com/blackboard/activity-list.html",
            "discovery_method": "public_web",
            "login_required": False,
            "parser_name": "public_activity_page",
            "crawl_frequency": "daily",
            "enabled": True,
            "reliability_level": "A",
            "last_success_at": None,
            "last_error": None,
            "consecutive_failures": 0,
        }
    )

    import game_promo_radar.discovery as discovery

    monkeypatch.setattr(
        discovery,
        "public_discovery_sources",
        lambda: [
            {
                "source_id": "bilibili_creator_activity",
                "source_name": "B站创作中心活动",
                "content_platform": "B站",
                "base_url": "https://www.bilibili.com/blackboard/activity-list.html",
                "reliability_level": "A",
            }
        ],
    )

    def fake_fetch(url, timeout=20):
        if url.endswith("activity-list.html"):
            return '<html><a href="https://www.bilibili.com/blackboard/activity-game.html">游戏投稿奖励活动</a></html>'
        return "<html><head><title>游戏投稿奖励活动</title></head><body>官方活动规则：创作者发布视频报名投稿，保底100元奖励，截止时间2999-01-01，主办方为平台官方。</body></html>"

    monkeypatch.setattr(discovery, "fetch_html", fake_fetch)
    monkeypatch.setattr(discovery, "SNAPSHOT_DIR", tmp_path / "snapshots")
    summary = run_public_sources(db, max_links_per_source=5)
    assert summary.discovered_link_count == 1
    assert summary.new_candidate_count == 1
    assert len(db.df("campaign_candidates")) == 1


def test_unknown_domains_become_source_discovery_candidates(tmp_path, monkeypatch):
    db = RadarDB(tmp_path / "radar.duckdb")

    import game_promo_radar.discovery as discovery

    monkeypatch.setattr(
        discovery,
        "search_results",
        lambda query, max_results=8: [
            SearchResult(title="游戏投稿奖励活动A", url="https://newsource.test/a", snippet="创作者发布视频报名，现金奖励"),
            SearchResult(title="游戏投稿奖励活动B", url="https://newsource.test/b", snippet="达人投稿征集，瓜分奖金"),
        ],
    )
    monkeypatch.setattr(discovery, "fetch_html", lambda url, timeout=20: "<html><body>创作者发布视频报名，现金奖励。</body></html>")
    monkeypatch.setattr(discovery, "SNAPSHOT_DIR", tmp_path / "snapshots")
    run_search(db, max_queries=1, max_results_per_query=2)
    sources = db.df("source_discovery_candidates")
    assert not sources.empty
    assert "newsource.test" in sources["domain"].tolist()

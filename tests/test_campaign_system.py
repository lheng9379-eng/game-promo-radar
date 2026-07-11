from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from game_promo_radar.adapters.manual import export_excel
from game_promo_radar.campaigns import (
    campaign_candidate_id,
    campaign_record_from_candidate,
    detect_risk_signals,
    generate_keyword_queries,
    parse_reward_numbers,
    score_campaign,
    source_reliability_for_url,
    validate_candidate,
)
from game_promo_radar.db import RadarDB
from game_promo_radar.models import Task
from game_promo_radar.sources import load_platform_sources, validate_source_config


def _candidate(**overrides):
    base = {
        "candidate_id": campaign_candidate_id("https://www.bilibili.com/blackboard/activity-a.html"),
        "source_id": "bilibili_creator_activity",
        "source_platform": "B站",
        "content_platform": "B站",
        "publisher_name": "B站",
        "publisher_type": "平台",
        "campaign_name": "测试游戏投稿奖励活动",
        "campaign_type": "视频征集",
        "source_url": "https://www.bilibili.com/blackboard/activity-a.html",
        "registration_url": "https://www.bilibili.com/blackboard/activity-a.html",
        "reward_model": "保底100元，优秀作品阶梯奖励，按播放量结算",
        "reward_min": 100,
        "reward_max": 1000,
        "reward_pool": 50000,
        "account_requirements": "无门槛，创作者发布视频并带话题投稿",
        "publish_requirements": "发布原创攻略视频",
        "material_requirements": "官方素材包可下载",
        "deadline": "2999-08-01",
        "raw_text": "官方活动规则：创作者发布视频，报名入口已开放，主办方为平台官方。",
    }
    return {**base, **overrides}


def test_data_source_config_test():
    sources = load_platform_sources(Path("PLATFORM_SOURCE_LIST.yaml"))
    errors = validate_source_config(sources)
    assert errors == []
    assert {"official_task_platform", "search_engine", "manual", "logged_in_browser"}.issubset({s["source_type"] for s in sources})
    taptap = next(source for source in sources if source["source_id"] == "taptap_creator")
    assert taptap["seed_urls"]


def test_candidate_dedupe_test(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    record = validate_candidate(_candidate())
    assert db.upsert_campaign_candidate(record) == "new"
    assert db.upsert_campaign_candidate({**record, "campaign_name": "更新标题"}) == "updated"
    assert len(db.df("campaign_candidates")) == 1


def test_activity_validity_test():
    valid = validate_candidate(_candidate(deadline="2999-01-01"), today=date(2026, 7, 11))
    expired = validate_candidate(_candidate(deadline="2026-01-01"), today=date(2026, 7, 11))
    assert valid["status"] == "验证通过"
    assert "仍在有效期:是" in valid["validation_notes"]
    assert expired["status"] != "验证通过"
    assert "仍在有效期:否" in expired["validation_notes"]


def test_official_source_reliability_test():
    assert source_reliability_for_url("https://www.gamepublisher.cn/task") == "A"
    assert source_reliability_for_url("https://www.taptap.cn/moment/1") == "B"
    assert source_reliability_for_url("https://random.example.com/post") == "D"


def test_risk_word_detection_test():
    level, signals = detect_risk_signals("投稿前要求先付费和押金，只能加私人微信，没有活动规则")
    assert level == "高"
    assert "先付费" in signals
    assert "押金" in signals


def test_reward_pool_and_expected_income_are_separate_test():
    numbers = parse_reward_numbers("总奖池10万元，保底100元，最高1000元")
    assert numbers["reward_pool"] == 100000
    scored = score_campaign(_candidate(reward_pool=100000, reward_min=100, reward_max=1000))
    assert scored.expected_income == 100
    assert scored.expected_income != 100000


def test_same_campaign_multi_source_merge_test(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    one = campaign_record_from_candidate(validate_candidate(_candidate()))
    two = campaign_record_from_candidate(validate_candidate(_candidate(source_platform="TapTap")))
    assert db.upsert_campaign(one) == "new"
    assert db.upsert_campaign(two) == "updated"
    assert len(db.df("campaigns")) == 1


def test_login_expired_handling_test(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    db.log_run("logged_in_browser", "https://pgy.xiaohongshu.com/", "blocked", "登录失效，需要用户手动重新登录", 0, 1, 0, 0)
    db.con.execute("update crawl_runs set login_state = ? where source_key = ?", ["expired", "logged_in_browser"])
    row = db.df("crawl_runs").iloc[0]
    assert row["status"] == "blocked"
    assert row["login_state"] == "expired"


def test_collect_failure_retry_test(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    db.log_run("source", "https://example.com", "blocked", "timeout", 0, 1, 0, 0)
    db.con.execute("update crawl_runs set retry_after = ? where source_key = ?", ["2026-07-12T09:00:00", "source"])
    row = db.df("crawl_runs").iloc[0]
    assert row["retry_after"] == "2026-07-12T09:00:00"


def test_source_link_jump_test(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    db.upsert_campaign_candidate(validate_candidate(_candidate()))
    row = db.df("campaign_candidates").iloc[0]
    assert str(row["source_url"]).startswith("https://")
    assert str(row["registration_url"]).startswith("https://")


def test_campaign_export_test(tmp_path):
    output = tmp_path / "campaigns.xlsx"
    df = pd.DataFrame([campaign_record_from_candidate(validate_candidate(_candidate()))])
    export_excel(df, output)
    exported = pd.read_excel(output)
    assert "campaign_name" in exported.columns
    assert "expected_income" in exported.columns


def test_keyword_query_combination_test():
    queries = generate_keyword_queries(games=["原神"], brands=["测试品牌"], platforms=["抖音"], industry_terms=["游戏"], max_queries=20)
    assert "原神 创作者招募" in queries
    assert "测试品牌 创作者招募" in queries
    assert "抖音 创作者招募" in queries


def test_candidate_from_task_stays_candidate_first(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    task = Task(
        "B站",
        "测试游戏",
        "投稿奖励活动",
        "https://www.bilibili.com/blackboard/activity-task.html",
        reward_description="保底100元",
        deadline="2999-01-01",
        account_requirements="无门槛",
        production_requirements="发布视频投稿",
    )
    db.upsert_tasks([task])
    assert len(db.df("tasks")) == 1
    assert db.df("campaign_candidates").empty

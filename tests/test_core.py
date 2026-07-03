from __future__ import annotations

from datetime import date

import pandas as pd

from game_promo_radar.analysis import analyze_task
from game_promo_radar.adapters.manual import import_excel, preview_excel, task_from_row
from game_promo_radar.adapters.public_web import (
    extract_page_content,
    identify_category,
    identify_platform,
    identify_settlement,
    recognize_promotion_task,
)
from game_promo_radar.db import RadarDB
from game_promo_radar.models import AccountProfile, DataSource, ImportRun, Task, TaskNote
from game_promo_radar.rules import deadline_status, display_value, is_missing


def test_task_dedupe(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    task = Task("抖音", "游戏A", "任务A", "https://example.com/a", task_id="A1")
    db.upsert_tasks([task, task])
    assert len(db.df("tasks")) == 1


def test_null_price_is_preserved_and_displayed(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    db.upsert_tasks([Task("快手", "游戏B", "未知单价", "https://example.com/b", unit_price=None)])
    row = db.df("tasks").iloc[0]
    assert pd.isna(row["unit_price"])
    assert display_value(row["unit_price"]) == "待确认"
    assert is_missing("NULL")


def test_deadline_status():
    assert deadline_status("2026-06-29", date(2026, 6, 30)) == "已截止"
    assert deadline_status("2026-07-02", date(2026, 6, 30)) == "即将截止"
    assert deadline_status("2026-07-20", date(2026, 6, 30)) == "进行中"
    assert deadline_status(None, date(2026, 6, 30)) == "待确认"


def test_analysis_recommends_clear_low_barrier_task():
    task = Task(
        "抖音",
        "游戏A",
        "高奖励任务",
        "https://example.com/a",
        unit_price=8,
        deadline="2999-01-01",
        account_requirements="无门槛",
        material_url="https://example.com/material",
        production_requirements="使用官方素材剪辑发布",
        confidence=0.9,
    ).to_record()
    result = analyze_task(task, {"median_views": 100000, "competition": "low"})
    assert result.feasibility in {"推荐做", "可以做"}
    assert result.difficulty == "简单"
    assert result.evidence


def test_game_task_keeps_legacy_defaults():
    task = Task("抖音", "游戏A", "任务A", "https://example.com/a").to_record()
    assert task["task_category"] == "game"
    assert task["is_game_related"] is True
    result = analyze_task(task)
    assert "游戏" in result.suitable_account_type


def test_analysis_marks_missing_information():
    task = Task("快手", "待确认", "公开通告", "https://example.com/b").to_record()
    result = analyze_task(task)
    assert result.feasibility == "信息不足"
    assert result.difficulty == "无法判断"
    assert "收益或奖励未获取到，不能推测。" in result.evidence
    assert "公开作品热度" in result.missing_fields


def test_analysis_detects_difficult_requirements():
    task = Task(
        "抖音",
        "游戏C",
        "真人原创任务",
        "https://example.com/c",
        unit_price=2,
        deadline="2999-01-01",
        account_requirements="万粉达人",
        material_url="https://example.com/material",
        production_requirements="需要真人出镜、原创拍摄、复杂剪辑",
    ).to_record()
    result = analyze_task(task, {"median_views": 5000, "competition": "high"})
    assert result.difficulty in {"较难", "困难"}
    assert any("真人出镜" in item for item in result.evidence)
    assert any("原创拍摄" in item for item in result.evidence)


def test_analysis_outputs_content_promotion_fields():
    task = Task(
        "小红书",
        "AI工具",
        "AI写作 App 下载奖励",
        "https://example.com/app",
        task_category="app",
        settlement_type="download",
        is_game_related=False,
        unit_price=5,
        deadline="2999-01-01",
        account_requirements="不限粉丝",
        material_url="https://example.com/material",
        production_requirements="教程演示",
    ).to_record()
    result = analyze_task(task)
    assert result.risk_level in {"low", "medium"}
    assert result.expected_value_score >= 1
    assert result.account_match_score >= 1
    assert "工具" in result.suitable_account_type


def test_account_profile_improves_matching_for_accepted_category():
    task = Task(
        "小红书",
        "AI工具",
        "AI写作 App 下载奖励",
        "https://example.com/app",
        task_category="app",
        settlement_type="download",
        content_form="note",
        target_account_type="AI工具,教程",
        is_game_related=False,
        unit_price=5,
        deadline="2999-01-01",
        account_requirements="不限粉丝",
        material_url="https://example.com/material",
        production_requirements="教程演示",
    ).to_record()
    profile = AccountProfile(
        "AI教程号",
        "小红书",
        "AI工具,教程",
        follower_count=15000,
        average_views=20000,
        content_forms="note",
        acceptable_categories="app",
    ).to_record()
    result = analyze_task(task, account_profile=profile)
    assert result.account_match_score >= 80
    assert result.worth_doing
    assert any("可承接范围" in item for item in result.evidence)


def test_analysis_blocks_high_risk_terms():
    task = Task(
        "抖音",
        "品牌活动",
        "刷量互赞推广",
        "https://example.com/risk",
        task_category="brand",
        is_game_related=False,
        unit_price=100,
        deadline="2999-01-01",
        account_requirements="无门槛",
        material_url="https://example.com/material",
        production_requirements="要求刷量和虚假互动",
    ).to_record()
    result = analyze_task(task)
    assert result.risk_level == "high"
    assert not result.worth_doing


def test_uncertain_settlement_is_high_risk_and_not_recommended():
    task = Task(
        "其他",
        "品牌活动",
        "高额奖励待定任务",
        "https://example.com/uncertain",
        task_category="brand",
        settlement_type="unknown",
        is_game_related=False,
        unit_price=100,
        deadline="2999-01-01",
        account_requirements="无门槛",
        material_url="https://example.com/material",
        production_requirements="规则可能调整，结算不保证，按平台最终审核",
    ).to_record()
    result = analyze_task(task)
    assert result.risk_level == "high"
    assert not result.worth_doing


def test_manual_import_accepts_null_string():
    task = task_from_row(
        {
            "platform": "抖音",
            "game_name": "游戏D",
            "task_name": "NULL奖励任务",
            "source_url": "https://example.com/d",
            "unit_price": "NULL",
            "material_url": "NULL",
        }
    )
    assert task.unit_price is None
    assert task.material_url is None


def test_manual_import_accepts_new_content_fields():
    task = task_from_row(
        {
            "platform": "小红书",
            "game_name": "AI工具",
            "task_name": "下载奖励",
            "source_url": "https://example.com/app",
            "task_category": "app",
            "settlement_type": "download",
            "content_form": "note",
            "target_account_type": "AI工具、教程",
            "is_game_related": "否",
        }
    )
    rec = task.to_record()
    assert rec["task_category"] == "app"
    assert rec["settlement_type"] == "download"
    assert rec["content_form"] == "note"
    assert rec["is_game_related"] is False


def test_manual_link_import_task_enters_library(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    task = task_from_row(
        {
            "platform": "抖音",
            "task_category": "brand",
            "settlement_type": "fixed_reward",
            "game_name": "品牌活动",
            "task_name": "新品话题挑战",
            "source_url": "https://example.com/brand-task",
            "reward_rule_text": "入围固定奖励 500 元",
            "deadline": "2999-01-01",
            "is_game_related": False,
        }
    )
    db.upsert_tasks([task])
    db.log_import_run(ImportRun("手动链接", "manual_link", 1))
    rows = db.df("tasks")
    runs = db.df("import_runs")
    assert len(rows) == 1
    assert rows.iloc[0]["task_category"] == "brand"
    assert runs.iloc[0]["source_type"] == "manual_link"


def test_excel_import_maps_common_chinese_fields(tmp_path):
    path = tmp_path / "tasks.xlsx"
    pd.DataFrame(
        [
            {
                "任务名称": "AI App 下载奖励",
                "平台": "小红书",
                "分类": "App 推广",
                "结算方式": "下载/注册",
                "奖励规则": "每有效下载 5 元",
                "链接": "https://example.com/app-download",
                "截止时间": "2999-01-01",
            }
        ]
    ).to_excel(path, index=False)
    preview = preview_excel(path)
    tasks = import_excel(path)
    assert preview.iloc[0]["task_name"] == "AI App 下载奖励"
    assert tasks[0].task_category == "app"
    assert tasks[0].settlement_type == "download"
    assert tasks[0].reward_rule_text == "每有效下载 5 元"


def test_repeated_collect_keeps_first_seen(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    first = Task("抖音", "游戏A", "任务A", "https://example.com/a", task_id="A1", first_seen_at="2026-01-01T00:00:00")
    second = Task("抖音", "游戏A", "任务A更新", "https://example.com/a", task_id="A1", first_seen_at="2026-02-01T00:00:00")
    db.upsert_tasks([first])
    db.upsert_tasks([second])
    row = db.df("tasks").iloc[0]
    assert row["first_seen_at"] == "2026-01-01T00:00:00"
    assert row["task_name"] == "任务A更新"


def test_duplicate_task_updates_without_extra_row(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    first = Task(
        "抖音",
        "对象A",
        "同一个任务",
        "https://example.com/same",
        reward_rule_text="播放奖励",
        first_seen_at="2026-01-01T00:00:00",
    )
    second = Task(
        "抖音",
        "对象B",
        "同一个任务",
        "https://example.com/same",
        reward_rule_text="播放奖励",
        production_requirements="更新后的制作要求",
        first_seen_at="2026-02-01T00:00:00",
    )
    db.upsert_tasks([first])
    db.upsert_tasks([second])
    rows = db.df("tasks")
    assert len(rows) == 1
    assert rows.iloc[0]["first_seen_at"] == "2026-01-01T00:00:00"
    assert rows.iloc[0]["production_requirements"] == "更新后的制作要求"


def test_task_result_note(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    db.add_task_note(TaskNote("k", "已发布，等待平台反馈"))
    notes = db.df("task_notes")
    assert notes.iloc[0]["note"] == "已发布，等待平台反馈"


def test_db_persists_new_content_fields(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    db.upsert_tasks(
        [
            Task(
                "小红书",
                "AI工具",
                "下载奖励",
                "https://example.com/app",
                task_category="app",
                settlement_type="download",
                content_form="note",
                target_account_type="AI工具",
                is_game_related=False,
            )
        ]
    )
    row = db.df("tasks").iloc[0]
    assert row["task_category"] == "app"
    assert row["settlement_type"] == "download"
    assert row["content_form"] == "note"
    assert bool(row["is_game_related"]) is False


def test_db_persists_account_profile(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    db.upsert_account_profile(
        AccountProfile(
            "本地探店号",
            "抖音",
            "探店,本地生活",
            follower_count=30000,
            average_views=18000,
            content_forms="short_video",
            real_person=True,
            acceptable_categories="local_life,brand",
        )
    )
    row = db.df("account_profiles").iloc[0]
    assert row["profile_key"] == "抖音|本地探店号".lower()
    assert row["acceptable_categories"] == "local_life,brand"


def test_data_source_enable_disable(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    source = DataSource(
        name="小红书蒲公英",
        platform="小红书",
        task_category="brand",
        collection_method="manual_link",
        link="https://example.com/source",
        enabled=True,
        frequency="weekly",
        notes="品牌合作任务",
    )
    db.upsert_data_source(source)
    row = db.df("data_sources").iloc[0]
    assert bool(row["enabled"]) is True
    db.set_data_source_enabled(row["source_key"], False)
    updated = db.df("data_sources").iloc[0]
    assert bool(updated["enabled"]) is False


def test_import_record_is_persisted(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    db.log_import_run(ImportRun("manual.xlsx", "excel", 3, 1, "partial", "第 4 行缺少链接"))
    row = db.df("import_runs").iloc[0]
    assert row["success_count"] == 3
    assert row["failure_count"] == 1
    assert row["error_reason"] == "第 4 行缺少链接"


def test_public_web_text_extraction():
    html = """
    <html><head><title>抖音创作者挑战赛</title><script>ignore()</script></head>
    <body><p>2026年07月01日 发布。参与投稿可获得播放量奖励。</p>
    <a href="/task">任务详情</a></body></html>
    """
    page = extract_page_content(html, "https://example.com/root")
    assert page["title"] == "抖音创作者挑战赛"
    assert "播放量奖励" in page["text"]
    assert "ignore()" not in page["text"]
    assert page["links"] == ["https://example.com/task"]
    assert page["published_at"] == "2026-07-01"


def test_keyword_platform_category_settlement_recognition():
    text = "小红书蒲公英达人任务，电商种草投稿，成交佣金结算。"
    assert identify_platform(text) == "小红书"
    assert identify_category(text) == "ecommerce"
    assert identify_settlement(text) == "sale_commission"


def test_public_web_candidate_preview_record():
    page = {
        "title": "快手磁力聚星品牌挑战赛奖励任务",
        "text": "创作者投稿参与挑战赛，固定奖励 500 元，按规则结算。",
        "links": ["https://example.com/signup"],
        "published_at": "2026-07-01",
    }
    candidates = recognize_promotion_task(page, "https://example.com/task")
    assert len(candidates) == 1
    record = candidates[0].to_record()
    assert record["platform"] == "快手"
    assert record["task_category"] in {"brand", "platform_incentive"}
    assert record["settlement_type"] == "fixed_reward"
    assert record["confidence"] >= 0.5
    assert record["source_url"] == "https://example.com/task"


def test_same_link_duplicate_updates_existing_task(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    first = Task(
        "抖音",
        "旧标题",
        "旧标题",
        "https://example.com/same-link",
        reward_rule_text="播放奖励",
        first_seen_at="2026-01-01T00:00:00",
    )
    second = Task(
        "抖音",
        "新标题",
        "新标题",
        "https://example.com/same-link",
        reward_rule_text="播放奖励更新",
        first_seen_at="2026-02-01T00:00:00",
    )
    db.upsert_tasks([first])
    db.upsert_tasks([second])
    rows = db.df("tasks")
    assert len(rows) == 1
    assert rows.iloc[0]["task_name"] == "新标题"
    assert rows.iloc[0]["reward_rule_text"] == "播放奖励更新"
    assert rows.iloc[0]["first_seen_at"] == "2026-01-01T00:00:00"


def test_public_web_crawl_record_written(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    db.log_import_run(ImportRun("品牌官网", "public_web", 2, 0, "ok", None))
    row = db.df("import_runs").iloc[0]
    assert row["source_type"] == "public_web"
    assert row["success_count"] == 2


def test_non_game_task_can_be_recorded_and_filtered(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    task = task_from_row(
        {
            "platform": "小红书",
            "game_name": "护肤品",
            "task_name": "电商种草佣金任务",
            "source_url": "https://example.com/ecommerce",
            "task_category": "ecommerce",
            "settlement_type": "sale_commission",
            "content_form": "note",
            "is_game_related": "否",
            "unit_price": 10,
        }
    )
    db.upsert_tasks([task])
    df = db.df("tasks")
    filtered = df[df["task_category"] == "ecommerce"]
    assert len(filtered) == 1
    result = analyze_task(filtered.iloc[0].to_dict())
    assert "好物" in result.suitable_account_type

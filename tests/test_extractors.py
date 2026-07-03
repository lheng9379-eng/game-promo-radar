from __future__ import annotations

from datetime import date
from pathlib import Path

from game_promo_radar.db import RadarDB
from game_promo_radar.extractors import extract_dates, extract_opportunity_fields
from game_promo_radar.intel import link_unlinked_intel, save_unlinked_intel
from game_promo_radar.models import Task


def test_extract_reward_summary_from_cash_text():
    fields = extract_opportunity_fields("《测试游戏》创作者激励活动，投稿优质视频可瓜分现金奖励，按播放量阶梯奖励结算。")
    assert fields["reward_summary"] is not None
    assert "现金" in fields["reward_summary"]
    assert "奖励" in fields["reward_summary"]


def test_extract_supported_date_formats():
    text = "活动时间 2026年7月1日 至 2026-07-15，投稿截止 7月20日。"
    dates = extract_dates(text, today=date(2026, 6, 1))
    assert "2026-07-01" in dates
    assert "2026-07-15" in dates
    assert "2026-07-20" in dates
    fields = extract_opportunity_fields(text)
    assert fields["deadline"] is not None


def test_extract_entry_requirements():
    fields = extract_opportunity_fields("报名门槛：账号需完成实名，粉丝大于1000，创作者需通过审核。")
    assert fields["entry_requirements"] is not None
    assert "粉丝" in fields["entry_requirements"]
    assert "实名" in fields["entry_requirements"]


def test_extract_material_and_production_requirements():
    fields = extract_opportunity_fields("官方素材包已开放下载，包含脚本模板和视频素材；投稿视频时长30秒以上，需竖屏原创录屏攻略。")
    assert fields["material_requirements"] is not None
    assert "素材包" in fields["material_requirements"]
    assert fields["production_requirements"] is not None
    assert "视频时长" in fields["production_requirements"]


def test_extract_high_risk_keywords():
    fields = extract_opportunity_fields("禁止搬运侵权内容，违规视频不结算，严重者进入黑名单。")
    assert fields["risk_keywords"] is not None
    assert fields["risk_level"] == "高"


def test_unlinked_intel_can_be_saved_and_linked(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    task = Task("TapTap", "测试游戏", "测试任务", "https://example.com/task")
    db.upsert_tasks([task])
    save_unlinked_intel(
        db,
        source_url="https://example.com/intel",
        page_title="线索页",
        fields={"task_name": "线索任务", "game_name": "测试游戏", "source_url": "https://example.com/intel"},
    )
    assert len(db.df("opportunity_unlinked_intel")) == 1
    link_unlinked_intel(db, "https://example.com/intel", task.dedupe_key())
    row = db.df("opportunity_unlinked_intel").iloc[0]
    assert row["linked_task_dedupe_key"] == task.dedupe_key()
    assert row["intel_status"] == "已确认"


def test_unlinked_source_url_dedupe(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    save_unlinked_intel(db, source_url="https://example.com/intel", page_title="第一次")
    save_unlinked_intel(db, source_url="https://example.com/intel", page_title="第二次")
    rows = db.df("opportunity_unlinked_intel")
    assert len(rows) == 1
    assert rows.iloc[0]["page_title"] == "第二次"

from __future__ import annotations

from pathlib import Path

import pandas as pd

from game_promo_radar.adapters.manual import export_excel
from game_promo_radar.analysis import analyze_task
from game_promo_radar.db import RadarDB
from game_promo_radar.intel import (
    DEMO_TASK_KEY,
    extension_excel_template,
    insert_demo_intel,
    load_intel_sources,
    save_pending_intel_link,
)
from game_promo_radar.models import Task


def test_intel_sources_yaml_can_be_loaded():
    sources = load_intel_sources(Path("config/intel_sources.yaml"))
    names = {source["source_name"] for source in sources}
    assert "TapTap 创作者活动" in names
    assert "Excel 导入" in names
    assert all(source.get("collect_method") in {"auto", "semi_auto", "manual"} for source in sources)


def test_manual_extended_intel_insert_succeeds(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    db.insert_record(
        "opportunity_heat_metrics",
        {
            "task_dedupe_key": "manual-task",
            "game_search_keyword": "测试游戏",
            "heat_source": "手动录入",
            "heat_index": 66,
            "heat_trend": "上升",
            "intel_status": "已补全",
        },
    )
    rows = db.df("opportunity_heat_metrics")
    assert len(rows) == 1
    assert rows.iloc[0]["intel_status"] == "已补全"


def test_semi_auto_link_saved_as_pending(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    html = "<html><head><title>测试情报页</title></head><body>这里有榜单排名和活动说明，需要人工补全字段。</body></html>"
    record = save_pending_intel_link(
        db,
        task_dedupe_key="task-1",
        source_url="https://example.com/intel",
        source_platform="TapTap",
        snapshot_dir=tmp_path / "snapshots",
        fetcher=lambda url: html,
    )
    rows = db.df("opportunity_intel_links")
    assert len(rows) == 1
    assert rows.iloc[0]["intel_status"] == "待确认"
    assert rows.iloc[0]["page_title"] == "测试情报页"
    assert Path(record["snapshot_path"]).exists()


def test_demo_intel_does_not_affect_real_task_analysis(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    task = Task("TapTap", "真实游戏", "真实任务", "https://example.com/real")
    db.upsert_tasks([task])
    insert_demo_intel(db)
    assert len(db.df("opportunity_heat_metrics")) == 1
    assert db.df("opportunity_heat_metrics").iloc[0]["task_dedupe_key"] == DEMO_TASK_KEY
    result = analyze_task(db.df("tasks").iloc[0].to_dict())
    assert result.feasibility == "信息不足"


def test_extension_excel_template_can_be_generated(tmp_path):
    template = extension_excel_template()
    assert "任务名称" in template.columns
    assert "样本视频链接" in template.columns
    assert "风险等级" in template.columns
    output = tmp_path / "template.xlsx"
    export_excel(template, output)
    assert output.exists()
    exported = pd.read_excel(output)
    assert "是否有脚本模板" in exported.columns

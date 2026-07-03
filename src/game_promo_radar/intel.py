from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

import pandas as pd
import yaml

from .adapters.base import save_snapshot
from .extractors import clean_text, extract_opportunity_fields, html_title as _extractor_html_title
from .models import now_iso
from .rules import is_missing

INTEL_STATUS_OPTIONS = ["待补全", "已补全", "已确认", "已忽略"]
DEMO_TASK_KEY = "sample/demo"


def load_intel_sources(path: str | Path = "config/intel_sources.yaml") -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("sources") or [])


def extension_excel_template() -> pd.DataFrame:
    columns = [
        "任务名称",
        "游戏名",
        "数据类型",
        "来源平台",
        "来源链接",
        "热度趋势",
        "榜单排名",
        "投放趋势",
        "样本视频链接",
        "点赞数",
        "评论数",
        "是否有官方素材",
        "是否有视频素材",
        "是否有脚本模板",
        "风险等级",
        "备注",
    ]
    return pd.DataFrame(columns=columns)


def fetch_public_page(url: str) -> str:
    req = Request(url, headers={"User-Agent": "game-promo-radar/0.5 intel-link"})
    with urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def html_title(html: str) -> str | None:
    return _extractor_html_title(html)


def clean_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", "\n", value)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


def page_summary(html: str, limit: int = 280) -> str | None:
    text = clean_text(html)
    if not text:
        return None
    return text[:limit]


def save_pending_intel_link(
    db,
    *,
    task_dedupe_key: str,
    source_url: str,
    source_platform: str | None = None,
    intel_type: str = "待识别",
    snapshot_dir: str | Path = "data/snapshots/intel",
    fetcher: Callable[[str], str] | None = None,
    extracted_fields: dict | None = None,
) -> dict:
    fetch = fetcher or fetch_public_page
    html = fetch(source_url)
    snapshot_path = save_snapshot(snapshot_dir, "intel_link", html)
    title = html_title(html)
    summary = page_summary(html)
    fields = extracted_fields or extract_opportunity_fields(f"{title or ''}\n{clean_text(html)}", source_url)
    requirements = "\n".join(
        item
        for item in [
            fields.get("entry_requirements"),
            fields.get("material_requirements"),
            fields.get("production_requirements"),
        ]
        if not is_missing(item)
    )
    record = {
        "task_dedupe_key": task_dedupe_key,
        "intel_type": intel_type,
        "source_platform": source_platform,
        "source_url": source_url,
        "page_title": title,
        "page_summary": summary,
        "snapshot_path": snapshot_path,
        "extracted_task_name": fields.get("task_name"),
        "extracted_game_name": fields.get("game_name"),
        "extracted_reward": fields.get("reward_summary"),
        "extracted_deadline": fields.get("deadline"),
        "extracted_requirements": requirements or None,
        "extracted_risk": fields.get("risk_keywords") or fields.get("risk_level"),
        "extracted_fields_json": json.dumps(fields, ensure_ascii=False),
        "intel_status": "待确认",
        "notes": "半自动链接保存，字段待人工确认。",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    db.upsert_latest_record("opportunity_intel_links", ["task_dedupe_key", "source_url"], record)
    return record


def save_unlinked_intel(
    db,
    *,
    source_url: str,
    page_title: str | None = None,
    page_summary: str | None = None,
    snapshot_path: str | None = None,
    source_platform: str | None = None,
    fields: dict | None = None,
    intel_status: str = "待确认",
) -> dict:
    fields = fields or {}
    clue_id = f"unlinked|{source_url}".lower()
    requirements = "\n".join(
        item
        for item in [
            fields.get("entry_requirements"),
            fields.get("material_requirements"),
            fields.get("production_requirements"),
        ]
        if not is_missing(item)
    )
    record = {
        "id": clue_id,
        "source_url": source_url,
        "page_title": page_title or fields.get("task_name"),
        "page_summary": page_summary or fields.get("raw_text_excerpt"),
        "snapshot_path": snapshot_path,
        "source_platform": source_platform or fields.get("source_platform"),
        "extracted_task_name": fields.get("task_name"),
        "extracted_game_name": fields.get("game_name"),
        "extracted_reward": fields.get("reward_summary"),
        "extracted_deadline": fields.get("deadline"),
        "extracted_requirements": requirements or None,
        "extracted_risk": fields.get("risk_keywords") or fields.get("risk_level"),
        "extracted_fields_json": json.dumps(fields, ensure_ascii=False),
        "linked_task_dedupe_key": None,
        "intel_status": intel_status,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    db.upsert_latest_record("opportunity_unlinked_intel", ["source_url"], record)
    return record


def link_unlinked_intel(db, source_url: str, task_dedupe_key: str) -> None:
    db.upsert_latest_record(
        "opportunity_unlinked_intel",
        ["source_url"],
        {
            "source_url": source_url,
            "linked_task_dedupe_key": task_dedupe_key,
            "intel_status": "已确认",
            "updated_at": now_iso(),
        },
    )


def ignore_unlinked_intel(db, source_url: str) -> None:
    db.upsert_latest_record(
        "opportunity_unlinked_intel",
        ["source_url"],
        {"source_url": source_url, "intel_status": "已忽略", "updated_at": now_iso()},
    )


def demo_intel_records() -> list[tuple[str, dict, str]]:
    stamp = now_iso()
    return [
        (
            "opportunity_heat_metrics",
            {
                "task_dedupe_key": DEMO_TASK_KEY,
                "game_search_keyword": "sample/demo 游戏热度",
                "heat_source": "sample/demo",
                "heat_index": 88,
                "heat_rank": 12,
                "heat_trend": "上升",
                "heat_snapshot_time": stamp,
                "heat_source_url": "sample/demo://heat",
                "heat_notes": "sample/demo 示例数据，不代表真实情报。",
                "intel_status": "已忽略",
            },
            "append",
        ),
        (
            "opportunity_sample_videos",
            {
                "task_dedupe_key": DEMO_TASK_KEY,
                "sample_platform": "B站",
                "sample_keyword": "sample/demo 爆款样本",
                "sample_video_title": "sample/demo 示例爆款视频",
                "sample_author_name": "sample/demo",
                "sample_like_count": 12000,
                "sample_comment_count": 300,
                "sample_content_type": "攻略讲解",
                "sample_hook_text": "sample/demo 示例钩子",
                "sample_source_url": "sample/demo://sample-video",
                "sample_snapshot_time": stamp,
                "intel_status": "已忽略",
            },
            "sample",
        ),
        (
            "opportunity_material_assets",
            {
                "task_dedupe_key": DEMO_TASK_KEY,
                "material_pack_url": "sample/demo://material-pack",
                "has_official_material": True,
                "has_video_material": True,
                "has_image_material": True,
                "has_script_template": True,
                "material_download_status": "无需下载",
                "material_notes": "sample/demo 示例素材完整度，不代表真实任务。",
                "intel_status": "已忽略",
            },
            "latest",
        ),
    ]


def insert_demo_intel(db) -> None:
    for table, record, mode in demo_intel_records():
        if mode == "sample":
            db.upsert_sample_video(record)
        elif mode == "latest":
            db.upsert_latest_record(table, ["task_dedupe_key", "material_pack_url"], record)
        else:
            existing = db.con.execute(
                f"select 1 from {table} where task_dedupe_key = ? and heat_source_url = ?",
                [record["task_dedupe_key"], record.get("heat_source_url")],
            ).fetchone()
            if not existing:
                db.insert_record(table, record)


def status_filter(df: pd.DataFrame, status: str) -> pd.DataFrame:
    if df.empty or status == "全部" or "intel_status" not in df.columns:
        return df
    return df[df["intel_status"].fillna("待补全") == status]


def is_demo_key(value: object) -> bool:
    return not is_missing(value) and str(value).startswith("sample/demo")

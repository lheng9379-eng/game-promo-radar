from __future__ import annotations

from pathlib import Path
import sys
from io import BytesIO

import pandas as pd
import streamlit as st
import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

from game_promo_radar.adapters.manual import export_excel, import_excel, task_from_row
from game_promo_radar.adapters.base import save_snapshot
from game_promo_radar.adapters.mediacrawler import MediaCrawlerAdapter
from game_promo_radar.adapters.public_web import DouyinGamePublisherAdapter, KuaishouSparkAdapter
from game_promo_radar.analysis import analyze_task
from game_promo_radar.db import RadarDB
from game_promo_radar.extractors import clean_text, extract_opportunity_fields
from game_promo_radar.intel import (
    INTEL_STATUS_OPTIONS,
    extension_excel_template,
    fetch_public_page,
    html_title,
    insert_demo_intel,
    link_unlinked_intel,
    load_intel_sources,
    page_summary,
    save_unlinked_intel,
    save_pending_intel_link,
    status_filter,
)
from game_promo_radar.models import Task, TaskNote, normalize_source_url
from game_promo_radar.online_collect import (
    DEFAULT_CURRENT_DETAIL_SEEDS,
    DEFAULT_PUBLIC_SOURCES,
    DEFAULT_DETAIL_SEEDS,
    DEFAULT_SEARCH_QUERIES,
    collect_detail_seed_urls,
    collect_from_search,
    collect_public_urls,
    discover_similar_detail_pages,
    is_high_value_pending,
    quality_summary,
    rediscover_details_from_existing_tasks,
    reparse_saved_snapshots,
)
from game_promo_radar.rules import deadline_status, display_value, is_missing, lifecycle_status
from game_promo_radar.scheduler import (
    AutoCollectConfig,
    append_auto_run,
    generate_alerts,
    load_auto_config,
    load_auto_runs,
    next_collect_time,
    run_auto_collect,
    save_auto_config,
    should_run_auto_collect,
)
from game_promo_radar.ui import (
    DIFFICULTY_COLORS,
    FEASIBILITY_COLORS,
    badge,
    dataframe_downloads,
    display_df,
    field_completeness,
    inject_css,
    reward_text,
    task_card,
    task_detail,
)

DB = RadarDB(ROOT / "data" / "game_promo_radar.duckdb")
AUTO_CONFIG_PATH = ROOT / "data" / "auto_collect_config.json"
AUTO_RUNS_PATH = ROOT / "data" / "auto_collect_runs.json"
ALERT_KEYS_PATH = ROOT / "data" / "alert_keys.json"


def sources_config() -> dict:
    with open(ROOT / "config" / "sources.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def scoring_config() -> dict:
    with open(ROOT / "config" / "scoring.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def excel_template_bytes(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="扩展情报导入模板")
    return buffer.getvalue()


def task_notes_text() -> dict[str, str]:
    notes = DB.df("task_notes")
    if notes.empty:
        return {}
    grouped = notes.groupby("task_dedupe_key")["note"].apply(lambda items: "\n".join(str(x) for x in items if not pd.isna(x)))
    return grouped.to_dict()


def extension_summary() -> dict[str, dict]:
    summary: dict[str, dict] = {}
    for row in DB.df("opportunity_heat_metrics").to_dict("records"):
        key = row.get("task_dedupe_key")
        if is_missing(key):
            continue
        current = summary.setdefault(key, {})
        current.update(
            {
                "heat_trend": row.get("heat_trend"),
                "heat_index": row.get("heat_index"),
                "heat_source": row.get("heat_source"),
                "heat_notes": row.get("heat_notes"),
            }
        )
    for row in DB.df("opportunity_app_ranks").to_dict("records"):
        key = row.get("task_dedupe_key")
        if is_missing(key):
            continue
        current = summary.setdefault(key, {})
        current.update(
            {
                "app_rank_source": row.get("app_rank_source"),
                "app_rank_position": row.get("app_rank_position"),
                "app_rank_change": row.get("app_rank_change"),
            }
        )
    for row in DB.df("opportunity_ad_intel").to_dict("records"):
        key = row.get("task_dedupe_key")
        if is_missing(key):
            continue
        current = summary.setdefault(key, {})
        current.update(
            {
                "ad_trend": row.get("ad_trend"),
                "ad_material_count": row.get("ad_material_count"),
                "ad_platforms": row.get("ad_platforms"),
            }
        )
    samples = DB.df("opportunity_sample_videos")
    if not samples.empty:
        for key, group in samples.groupby("task_dedupe_key"):
            current = summary.setdefault(key, {})
            likes = group["sample_like_count"].dropna().tolist() if "sample_like_count" in group.columns else []
            current["sample_count"] = len(group)
            current["top_sample_like_count"] = max(likes) if likes else None
            top = group.sort_values("sample_like_count", ascending=False, na_position="last").iloc[0]
            current["top_sample_title"] = top.get("sample_video_title")
            current["top_sample_url"] = top.get("sample_source_url")
    for row in DB.df("opportunity_material_assets").to_dict("records"):
        key = row.get("task_dedupe_key")
        if is_missing(key):
            continue
        current = summary.setdefault(key, {})
        bool_fields = ["has_official_material", "has_video_material", "has_image_material", "has_bgm", "has_script_template", "has_gameplay_recording"]
        material_score = sum(2 for field in bool_fields if not is_missing(row.get(field)) and bool(row.get(field)))
        current.update(
            {
                "has_official_material": row.get("has_official_material"),
                "has_video_material": row.get("has_video_material"),
                "has_script_template": row.get("has_script_template"),
                "material_score": material_score,
                "material_pack_url": row.get("material_pack_url"),
                "material_notes": row.get("material_notes"),
            }
        )
    risk_order = {"高": 3, "中": 2, "低": 1, "未知": 0}
    for row in DB.df("opportunity_risk_signals").to_dict("records"):
        key = row.get("task_dedupe_key")
        if is_missing(key):
            continue
        risks = [row.get("copyright_risk"), row.get("settlement_risk"), row.get("content_risk")]
        level = row.get("risk_level") or max((str(risk) for risk in risks if not is_missing(risk)), key=lambda value: risk_order.get(value, 0), default="未知")
        current = summary.setdefault(key, {})
        current.update({"risk_level": level, "risk_notes": row.get("risk_notes"), "risk_keywords": row.get("risk_keywords")})
    return summary


def analyzed_tasks() -> pd.DataFrame:
    df = DB.df("tasks")
    if df.empty:
        return df
    notes = task_notes_text()
    extensions = extension_summary()
    config = scoring_config()
    rows = []
    for task in df.to_dict("records"):
        task = {**task, **extensions.get(task.get("dedupe_key"), {})}
        result = analyze_task(task, config=config)
        row = {
            **task,
            "可做性": result.feasibility,
            "制作难度": result.difficulty,
            "判断依据": "\n".join(result.evidence),
            "未获取字段": "、".join(result.missing_fields) if result.missing_fields else "",
            "截止状态": deadline_status(task.get("deadline")),
            "生命周期": lifecycle_status(task.get("start_time"), task.get("deadline")),
            "result_note": notes.get(task.get("dedupe_key")),
        }
        row["奖励/收益"] = reward_text(row)
        row["完整度"] = field_completeness(row)
        row["热度趋势"] = row.get("heat_trend")
        row["榜单排名"] = row.get("app_rank_position")
        row["素材完整度"] = row.get("material_score")
        row["风险等级"] = row.get("risk_level")
        row["爆款样本数量"] = row.get("sample_count")
        row["热度指数"] = row.get("heat_index")
        row["榜单来源"] = row.get("app_rank_source")
        row["买量趋势"] = row.get("ad_trend")
        row["投放素材数量"] = row.get("ad_material_count")
        row["最高点赞样本"] = row.get("top_sample_like_count")
        row["是否有官方素材"] = row.get("has_official_material")
        row["是否有视频素材"] = row.get("has_video_material")
        row["是否有脚本模板"] = row.get("has_script_template")
        row["素材完整度评分"] = row.get("material_score")
        row["风险备注"] = row.get("risk_notes")
        if is_missing(row.get("value_keywords")):
            row["value_keywords"] = "、".join(
                term for term in ["奖励", "现金", "激励", "投稿", "活动时间", "截止", "二创", "攻略征集"] if term in str(row)
            ) or None
        row["高价值待确认"] = row["可做性"] == "信息不足" and is_high_value_pending(row)
        rows.append(row)
    return pd.DataFrame(rows)


def recent_collect_time() -> str:
    logs = DB.df("crawl_runs")
    if logs.empty or "created_at" not in logs.columns:
        return "暂无"
    return str(logs["created_at"].dropna().max() or "暂无")


def filtered_tasks(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    with st.container(border=True):
        col1, col2, col3, col4 = st.columns(4)
        platforms = sorted([x for x in df["platform"].dropna().unique().tolist() if x])
        feasibilities = ["推荐做", "可以做", "观望", "不建议做", "信息不足"]
        difficulties = ["简单", "一般", "较难", "困难", "无法判断"]
        deadline_states = ["进行中", "即将开始", "即将截止", "已截止", "待确认"]
        selected_platforms = col1.multiselect("平台", platforms, default=platforms)
        selected_feasibility = col2.multiselect("可做性", feasibilities, default=feasibilities)
        selected_difficulty = col3.multiselect("制作难度", difficulties, default=difficulties)
        selected_deadline = col4.multiselect("生命周期", deadline_states, default=deadline_states)

        col5, col6, col7, col8 = st.columns(4)
        completeness = col5.select_slider("信息完整度", options=["全部", "低于40%", "40%-80%", "80%以上"], value="全部")
        has_reward = col6.selectbox("是否有奖励", ["全部", "有奖励", "无奖励"])
        real_person = col7.selectbox("是否需要真人出镜", ["全部", "需要", "不需要/未知"])
        original = col8.selectbox("是否原创拍摄", ["全部", "需要", "不需要/未知"])
        query = st.text_input("搜索任务名 / 游戏名 / 来源链接", placeholder="输入关键词")

    result = df.copy()
    if selected_platforms:
        result = result[result["platform"].isin(selected_platforms)]
    result = result[result["可做性"].isin(selected_feasibility)]
    result = result[result["制作难度"].isin(selected_difficulty)]
    result = result[result["生命周期"].isin(selected_deadline)]
    if completeness == "低于40%":
        result = result[result["完整度"] < 0.4]
    elif completeness == "40%-80%":
        result = result[(result["完整度"] >= 0.4) & (result["完整度"] < 0.8)]
    elif completeness == "80%以上":
        result = result[result["完整度"] >= 0.8]
    if has_reward == "有奖励":
        result = result[~result["奖励/收益"].apply(is_missing)]
    elif has_reward == "无奖励":
        result = result[result["奖励/收益"].apply(is_missing)]
    if real_person == "需要":
        result = result[result["requires_real_person"] == True]
    elif real_person == "不需要/未知":
        result = result[result["requires_real_person"] != True]
    if original == "需要":
        result = result[result["requires_original_shooting"] == True]
    elif original == "不需要/未知":
        result = result[result["requires_original_shooting"] != True]
    if query.strip():
        q = query.strip().lower()
        haystack = (
            result["task_name"].fillna("").astype(str)
            + " "
            + result["game_name"].fillna("").astype(str)
            + " "
            + result["source_url"].fillna("").astype(str)
        ).str.lower()
        result = result[haystack.str.contains(q, regex=False)]
    return result


def core_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    table = df.copy()
    table["平台"] = table["platform"].apply(display_value)
    table["游戏"] = table["game_name"].apply(display_value)
    table["任务"] = table["task_name"].apply(display_value)
    table["奖励"] = table["奖励/收益"].apply(display_value)
    table["截止"] = table["deadline"].apply(display_value)
    table["生命周期"] = table["生命周期"].apply(display_value)
    table["更新时间"] = table["last_updated_at"].apply(display_value)
    table["来源链接"] = table["source_url"]
    table["详情"] = "下方展开"
    return table[
        [
            "平台",
            "游戏",
            "任务",
            "奖励",
            "截止",
            "生命周期",
            "热度趋势",
            "榜单排名",
            "素材完整度",
            "风险等级",
            "爆款样本数量",
            "可做性",
            "制作难度",
            "完整度",
            "更新时间",
            "来源链接",
            "详情",
        ]
    ]


def source_link_column_config(column_name: str = "来源链接") -> dict:
    return {
        column_name: st.column_config.LinkColumn(
            column_name,
            display_text="打开来源",
            width="small",
        )
    }


def kpi_dashboard(df: pd.DataFrame) -> None:
    today = pd.Timestamp.today().date().isoformat()
    total = len(df)
    today_new = int(df["first_seen_at"].astype(str).str.startswith(today).sum()) if not df.empty else 0
    recommended = int((df["可做性"] == "推荐做").sum()) if not df.empty else 0
    doable = int((df["可做性"] == "可以做").sum()) if not df.empty else 0
    soon = int((df["截止状态"] == "即将截止").sum()) if not df.empty else 0
    insufficient = int((df["可做性"] == "信息不足").sum()) if not df.empty else 0
    active = int(df["生命周期"].isin(["进行中", "即将开始", "即将截止"]).sum()) if not df.empty else 0
    expired = int((df["生命周期"] == "已截止").sum()) if not df.empty else 0
    valid_recommended = int(((df["可做性"] == "推荐做") & df["生命周期"].isin(["进行中", "即将开始", "即将截止"])).sum()) if not df.empty else 0
    valid_doable = int(((df["可做性"] == "可以做") & df["生命周期"].isin(["进行中", "即将开始", "即将截止"])).sum()) if not df.empty else 0
    completeness = round(float(df["完整度"].mean()), 2) if not df.empty else 0.0
    cols = st.columns(12)
    cols[0].metric("总任务数", total)
    cols[1].metric("今日新增", today_new)
    cols[2].metric("推荐做", recommended)
    cols[3].metric("可以做", doable)
    cols[4].metric("即将截止", soon)
    cols[5].metric("信息不足", insufficient)
    cols[6].metric("字段完整率", completeness)
    cols[7].metric("当前有效", active)
    cols[8].metric("已截止", expired)
    cols[9].metric("推荐有效", valid_recommended)
    cols[10].metric("可以做有效", valid_doable)
    cols[11].metric("最近采集时间", recent_collect_time())


def priority_section(df: pd.DataFrame) -> None:
    st.subheader("今日优先处理")
    ordered = df.sort_values(["完整度", "last_updated_at"], ascending=[False, False]) if not df.empty else df
    active_mask = ordered["生命周期"].isin(["进行中", "即将开始", "即将截止"])
    recommended = ordered[(ordered["可做性"] == "推荐做") & active_mask].head(3)
    doable = ordered[(ordered["可做性"] == "可以做") & active_mask].head(3)
    soon = ordered[(ordered["生命周期"] == "即将截止") & (ordered["可做性"] != "不建议做")].head(3)
    potential = ordered[ordered.get("高价值待确认", False) == True].head(3)
    high_value_count = int((df.get("高价值待确认", False) == True).sum()) if not df.empty else 0
    if high_value_count:
        st.info(f"当前有 {high_value_count} 条高价值待确认任务，可在“高价值待确认”页继续追踪。")
    columns = st.columns(4)
    groups = [
        ("推荐做且有效", recommended, "暂无推荐做且仍有效的任务。"),
        ("可以做且有效", doable, "暂无可以做且仍有效的任务。"),
        ("即将截止任务", soon, "暂无即将截止任务。"),
        ("高价值待确认", potential, "暂无高价值待确认任务。"),
    ]
    for column, (title, group, empty_text) in zip(columns, groups):
        with column:
            st.markdown(f"**{title}**")
            if group.empty:
                st.info(empty_text)
            else:
                for idx, row in group.iterrows():
                    task_card(row.to_dict(), f"priority-{idx}")


def today_new_section(df: pd.DataFrame) -> None:
    st.subheader("今日新增商机")
    if df.empty:
        st.info("暂无今日新增商机。")
        return
    today = pd.Timestamp.today().date().isoformat()
    today_new = df[df["first_seen_at"].astype(str).str.startswith(today)]
    if today_new.empty:
        st.info("暂无今日新增商机。")
        return
    table = core_table(today_new.sort_values("first_seen_at", ascending=False))
    st.dataframe(
        display_df(table),
        width="stretch",
        hide_index=True,
        column_config=source_link_column_config(),
    )


def merge_collect_results(left, right):
    left.tasks.extend(right.tasks)
    left.new_count += right.new_count
    left.updated_count += right.updated_count
    left.new_keys.extend(right.new_keys)
    left.updated_keys.extend(right.updated_keys)
    left.success_count += right.success_count
    left.failure_count += right.failure_count
    left.failures.extend(right.failures)
    left.entry_page_count += right.entry_page_count
    left.candidate_count += right.candidate_count
    left.filtered_count += right.filtered_count
    left.written_count += right.written_count
    left.quality = right.quality or left.quality
    return left


def quality_snapshot(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "字段完整率": 0.0,
            "信息不足数量": 0,
            "推荐做数量": 0,
            "可以做数量": 0,
            "仍缺字段最多的平台": "暂无",
        }
    missing_by_platform = (
        df[df["可做性"] == "信息不足"]
        .groupby(df["platform"].fillna("待确认"))
        .size()
        .sort_values(ascending=False)
    )
    return {
        "字段完整率": round(float(df["完整度"].mean()), 2),
        "信息不足数量": int((df["可做性"] == "信息不足").sum()),
        "推荐做数量": int((df["可做性"] == "推荐做").sum()),
        "可以做数量": int((df["可做性"] == "可以做").sum()),
        "仍缺字段最多的平台": str(missing_by_platform.index[0]) if not missing_by_platform.empty else "暂无",
    }


def seed_store_path() -> Path:
    return ROOT / "data" / "detail_seeds.txt"


def load_seed_urls() -> list[str]:
    path = seed_store_path()
    defaults = [url for _, _, url in DEFAULT_CURRENT_DETAIL_SEEDS] + [url for _, _, url in DEFAULT_DETAIL_SEEDS]
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(defaults), encoding="utf-8")
        return defaults
    stored = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    merged = list(dict.fromkeys(stored + defaults))
    if merged != stored:
        path.write_text("\n".join(merged), encoding="utf-8")
    return merged


def save_seed_urls(urls: list[str]) -> None:
    seed_store_path().write_text("\n".join(dict.fromkeys(urls)), encoding="utf-8")


def seed_status_table(df: pd.DataFrame, urls: list[str]) -> pd.DataFrame:
    rows = []
    for url in urls:
        match = df[df["source_url"].astype(str) == url] if not df.empty and "source_url" in df.columns else pd.DataFrame()
        if match.empty:
            rows.append({"种子URL": url, "状态": "未采集/未写入", "任务": "待确认", "字段完整度": "待确认", "可做性": "待确认"})
        else:
            row = match.iloc[0]
            rows.append(
                {
                    "种子URL": url,
                    "状态": "已写入",
                    "任务": display_value(row.get("task_name")),
                    "字段完整度": row.get("完整度"),
                    "可做性": row.get("可做性"),
                }
            )
    return pd.DataFrame(rows)


def import_extended_excel_rows(df: pd.DataFrame, tasks: list) -> None:
    for row, task in zip(df.to_dict("records"), tasks):
        key = task.dedupe_key()
        if not is_missing(row.get("热度趋势")) or not is_missing(row.get("热度指数")):
            DB.insert_record(
                "opportunity_heat_metrics",
                {
                    "task_dedupe_key": key,
                    "heat_trend": row.get("热度趋势"),
                    "heat_index": row.get("热度指数"),
                    "heat_source": row.get("热度来源"),
                    "heat_notes": row.get("热度备注"),
                },
            )
        if not is_missing(row.get("榜单排名")) or not is_missing(row.get("榜单来源")):
            DB.insert_record(
                "opportunity_app_ranks",
                {
                    "task_dedupe_key": key,
                    "app_rank_source": row.get("榜单来源"),
                    "app_rank_position": row.get("榜单排名"),
                },
            )
        if not is_missing(row.get("买量趋势")) or not is_missing(row.get("投放素材数量")):
            DB.insert_record(
                "opportunity_ad_intel",
                {
                    "task_dedupe_key": key,
                    "ad_trend": row.get("买量趋势"),
                    "ad_material_count": row.get("投放素材数量"),
                },
            )
        if not is_missing(row.get("样本视频链接")):
            DB.upsert_sample_video(
                {
                    "task_dedupe_key": key,
                    "sample_video_title": row.get("样本视频标题"),
                    "sample_like_count": row.get("样本点赞数"),
                    "sample_source_url": row.get("样本视频链接"),
                }
            )
        if any(not is_missing(row.get(col)) for col in ["是否有官方素材", "是否有视频素材", "是否有脚本模板"]):
            DB.upsert_latest_record(
                "opportunity_material_assets",
                ["task_dedupe_key", "material_pack_url"],
                {
                    "task_dedupe_key": key,
                    "material_pack_url": row.get("素材包链接") or "manual://default",
                    "has_official_material": row.get("是否有官方素材"),
                    "has_video_material": row.get("是否有视频素材"),
                    "has_script_template": row.get("是否有脚本模板"),
                    "material_notes": row.get("素材备注"),
                },
            )
        if not is_missing(row.get("风险等级")) or not is_missing(row.get("风险备注")):
            level = row.get("风险等级")
            DB.upsert_latest_record(
                "opportunity_risk_signals",
                ["task_dedupe_key"],
                {
                    "task_dedupe_key": key,
                    "copyright_risk": level,
                    "settlement_risk": level,
                    "content_risk": level,
                    "risk_notes": row.get("风险备注"),
                },
            )


def source_url_exists(source_url: str) -> bool:
    tasks = DB.df("tasks")
    if tasks.empty or is_missing(source_url):
        return False
    normalized = normalize_source_url(source_url)
    return any(normalize_source_url(url) == normalized for url in tasks["source_url"].dropna().astype(str).tolist())


def similar_task_hint(fields: dict) -> str | None:
    tasks = DB.df("tasks")
    if tasks.empty:
        return None
    task_name = str(fields.get("task_name") or "")
    game_name = str(fields.get("game_name") or "")
    for _, row in tasks.iterrows():
        same_game = game_name and game_name == str(row.get("game_name") or "")
        existing_task = str(row.get("task_name") or "")
        same_task = task_name and (task_name in existing_task or existing_task in task_name)
        if same_game and same_task:
            return f"可能重复：{row.get('platform')} / {row.get('game_name')} / {row.get('task_name')}"
    return None


def task_from_extracted_fields(fields: dict, snapshot_path: str | None = None) -> Task:
    source_url = fields.get("source_url") or "manual://intel-link"
    task_name = fields.get("task_name") or fields.get("reward_summary") or "公开情报线索"
    value_keywords = "、".join(
        value
        for value in [
            fields.get("heat_keywords"),
            fields.get("app_rank_keywords"),
            fields.get("ad_keywords"),
            fields.get("material_keywords"),
            fields.get("risk_keywords"),
        ]
        if not is_missing(value)
    )
    return Task(
        platform=fields.get("source_platform") or "公开网页",
        game_name=fields.get("game_name"),
        task_name=str(task_name)[:120],
        page_title=fields.get("task_name"),
        reward_description=fields.get("reward_summary"),
        deadline=fields.get("deadline"),
        account_requirements=fields.get("entry_requirements"),
        material_url=fields.get("material_requirements"),
        production_requirements=fields.get("production_requirements"),
        source_url=str(source_url),
        raw_snapshot=snapshot_path,
        value_keywords=value_keywords or None,
        confidence=0.55,
    )


def persist_extracted_extensions(task_key: str, fields: dict) -> None:
    if not is_missing(fields.get("material_requirements")):
        material_text = str(fields.get("material_requirements") or "")
        DB.upsert_latest_record(
            "opportunity_material_assets",
            ["task_dedupe_key", "material_pack_url"],
            {
                "task_dedupe_key": task_key,
                "material_pack_url": fields.get("source_url") or f"manual://material/{task_key}",
                "material_notes": material_text,
                "has_official_material": "官方素材" in material_text,
                "has_video_material": "视频素材" in material_text,
                "has_script_template": "脚本" in material_text or "模板" in material_text,
                "intel_status": "待确认",
            },
        )
    if not is_missing(fields.get("risk_keywords")) or fields.get("risk_level") in {"高", "中"}:
        DB.upsert_latest_record(
            "opportunity_risk_signals",
            ["task_dedupe_key"],
            {
                "task_dedupe_key": task_key,
                "risk_keywords": fields.get("risk_keywords"),
                "risk_level": fields.get("risk_level"),
                "risk_notes": fields.get("raw_text_excerpt"),
                "intel_status": "待确认",
            },
        )


def load_alert_keys() -> set[str]:
    if not ALERT_KEYS_PATH.exists():
        return set()
    import json

    return set(json.loads(ALERT_KEYS_PATH.read_text(encoding="utf-8")))


def save_alert_keys(keys: set[str]) -> None:
    import json

    ALERT_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERT_KEYS_PATH.write_text(json.dumps(sorted(keys), ensure_ascii=False, indent=2), encoding="utf-8")


def maybe_run_scheduled_collect() -> None:
    config = load_auto_config(AUTO_CONFIG_PATH)
    runs = load_auto_runs(AUTO_RUNS_PATH)
    last_run = runs[-1]["created_at"] if runs else None
    if should_run_auto_collect(config, last_run):
        record = run_auto_collect(DB, config, ROOT / "data" / "snapshots", ROOT)
        append_auto_run(AUTO_RUNS_PATH, record)
        st.toast("自动采集已完成", icon="✅")


st.set_page_config(page_title="内容推广商机雷达", layout="wide")
inject_css()
maybe_run_scheduled_collect()
st.title("内容推广商机雷达")
st.caption("个人本地公开情报工具：覆盖游戏、App、电商种草、本地生活、短剧、品牌活动和平台激励，判断推广任务是否值得做，以及制作难度是多少。")

df = analyzed_tasks()
kpi_dashboard(df)

tabs = st.tabs(["首页", "情报库", "网上采集", "高价值待确认", "扩展情报", "历史任务", "截止提醒", "热度分析", "导入导出", "数据源", "结果备注", "运行日志"])

with tabs[0]:
    if df.empty:
        st.info("暂无任务。请先运行网上采集或导入 Excel。")
    else:
        st.subheader("今日提醒")
        recent_runs = load_auto_runs(AUTO_RUNS_PATH)
        latest_summary = recent_runs[-1] if recent_runs else None
        alerts = generate_alerts(df, load_alert_keys(), latest_summary)
        if alerts:
            save_alert_keys(load_alert_keys() | {item["key"] for item in alerts})
            alert_df = pd.DataFrame(alerts)[["type", "task", "reason"]].rename(columns={"type": "提醒", "task": "任务", "reason": "原因"})
            st.dataframe(display_df(alert_df), width="stretch", hide_index=True)
        else:
            st.info("暂无新的本地提醒。")
        today_new_section(df)
        priority_section(df)

with tabs[1]:
    st.subheader("情报库")
    filtered = filtered_tasks(df)
    table = core_table(filtered)
    st.dataframe(
        display_df(table),
        width="stretch",
        hide_index=True,
        column_config=source_link_column_config(),
    )
    st.markdown("**任务详情**")
    if filtered.empty:
        st.info("没有符合筛选条件的任务。")
    else:
        for idx, row in filtered.head(40).iterrows():
            title = f"{display_value(row.get('platform'))} / {display_value(row.get('game_name'))} / {display_value(row.get('task_name'))}"
            with st.expander(title, expanded=False):
                st.markdown(badge(row.get("可做性"), FEASIBILITY_COLORS) + badge(row.get("制作难度"), DIFFICULTY_COLORS), unsafe_allow_html=True)
                task_detail(row.to_dict(), f"library-{idx}")

with tabs[2]:
    st.subheader("网上采集")
    st.caption("只采集公开页面；不采集私信、不自动报名、不采集自有账号后台数据。")
    st.markdown("**每日自动采集**")
    auto_config = load_auto_config(AUTO_CONFIG_PATH)
    with st.container(border=True):
        col_auto1, col_auto2, col_auto3 = st.columns(3)
        auto_enabled = col_auto1.toggle("启用自动采集", value=auto_config.enabled)
        auto_time = col_auto2.text_input("每日采集时间", value=auto_config.daily_time, placeholder="09:00")
        auto_active_only = col_auto3.checkbox("只采集有效期任务", value=auto_config.active_only, key="auto_collect_active_only")
        col_scope1, col_scope2, col_scope3, col_scope4 = st.columns(4)
        auto_current = col_scope1.checkbox("当前有效种子池", value=auto_config.use_current_seeds)
        auto_all = col_scope2.checkbox("全部历史种子池", value=auto_config.use_all_history_seeds)
        auto_similar = col_scope3.checkbox("同类页面发现", value=auto_config.use_similar_discovery)
        auto_search = col_scope4.checkbox("关键词搜索", value=auto_config.use_keyword_search)
        new_config = AutoCollectConfig(
            enabled=auto_enabled,
            daily_time=auto_time,
            use_current_seeds=auto_current,
            use_all_history_seeds=auto_all,
            use_similar_discovery=auto_similar,
            use_keyword_search=auto_search,
            active_only=auto_active_only,
        )
        next_time = next_collect_time(new_config)
        runs = load_auto_runs(AUTO_RUNS_PATH)
        st.write(f"下一次采集时间：{display_value(next_time.replace(microsecond=0).isoformat() if next_time else None)}")
        st.write(f"最近一次自动采集时间：{display_value(runs[-1].get('created_at') if runs else None)}")
        st.write(f"自动采集是否启用：{'启用' if new_config.enabled else '停用'}")
        col_save, col_run_now = st.columns(2)
        if col_save.button("保存自动采集设置", width="stretch"):
            save_auto_config(new_config, AUTO_CONFIG_PATH)
            st.success("已保存自动采集设置。")
        if col_run_now.button("立即运行一次自动采集", width="stretch"):
            save_auto_config(new_config, AUTO_CONFIG_PATH)
            record = run_auto_collect(DB, new_config, ROOT / "data" / "snapshots", ROOT)
            append_auto_run(AUTO_RUNS_PATH, record)
            st.success(f"自动采集完成：新增 {record['new_count']} 条，失败 {record['failure_count']} 条。")
            st.rerun()
        recent_runs = load_auto_runs(AUTO_RUNS_PATH)[-7:]
        st.markdown("**最近 7 次自动采集结果**")
        if recent_runs:
            st.dataframe(display_df(pd.DataFrame(recent_runs)), width="stretch", hide_index=True)
        else:
            st.info("暂无自动采集记录。")

    source_labels = {f"{name} - {url}": (name, platform, url) for name, platform, url in DEFAULT_PUBLIC_SOURCES}
    selected_labels = st.multiselect("选择采集源", list(source_labels.keys()), default=list(source_labels.keys()))
    scale = st.radio("采集规模", ["小批量", "标准", "深度"], horizontal=True)
    include_search = st.checkbox("包含关键词搜索采集", value=True)
    scale_map = {"小批量": 3, "标准": 5, "深度": 8}
    progress = st.progress(0)
    status = st.empty()
    col_run, col_reparse, col_discover = st.columns(3)
    if col_run.button("一键开始采集", type="primary", width="stretch"):
        selected_sources = [source_labels[label] for label in selected_labels]
        status.write("正在采集入口页并发现候选详情页...")
        progress.progress(15)
        result = collect_public_urls(DB, selected_sources, ROOT / "data" / "snapshots", pause_seconds=0.5)
        progress.progress(55)
        if include_search:
            status.write("正在执行关键词搜索采集...")
            search_result = collect_from_search(
                DB,
                DEFAULT_SEARCH_QUERIES,
                ROOT / "data" / "snapshots",
                max_results_per_query=scale_map[scale],
            )
            result = merge_collect_results(result, search_result)
        DB.log_run(
            "ui_online_collect",
            ",".join(url for _, _, url in selected_sources),
            "ok" if result.success_count else "blocked",
            "; ".join(result.failures),
            result.success_count,
            result.failure_count,
            result.new_count,
            result.updated_count,
        )
        progress.progress(100)
        status.success("采集完成。")
        st.session_state["last_online_collect"] = {
            "entry_page_count": result.entry_page_count,
            "candidate_count": result.candidate_count,
            "written_count": result.written_count,
            "filtered_count": result.filtered_count,
            "failure_count": result.failure_count,
            "new_count": result.new_count,
            "updated_count": result.updated_count,
            "quality": result.quality,
            "failures": result.failures,
        }
        st.rerun()
    if col_reparse.button("重新解析详情页", width="stretch"):
        before_df = analyzed_tasks()
        before = quality_snapshot(before_df)
        status.write("正在读取已保存 HTML 快照并重新提取字段...")
        progress.progress(30)
        result = reparse_saved_snapshots(DB, ROOT)
        progress.progress(100)
        after_df = analyzed_tasks()
        after = quality_snapshot(after_df)
        DB.log_run(
            "ui_reparse_snapshots",
            "saved_snapshots",
            "ok" if result.success_count else "blocked",
            "; ".join(result.failures),
            result.success_count,
            result.failure_count,
            0,
            result.updated_count,
        )
        st.session_state["last_reparse_compare"] = {"before": before, "after": after}
        st.session_state["last_online_collect"] = {
            "entry_page_count": 0,
            "candidate_count": result.candidate_count,
            "written_count": result.written_count,
            "filtered_count": result.filtered_count,
            "failure_count": result.failure_count,
            "new_count": 0,
            "updated_count": result.updated_count,
            "quality": result.quality,
            "failures": result.failures,
        }
        status.success("重新解析完成。")
        st.rerun()
    if col_discover.button("追踪详情链接", width="stretch"):
        before_df = analyzed_tasks()
        before = quality_snapshot(before_df)
        status.write("正在从高价值待确认页面继续发现详情链接...")
        progress.progress(20)
        result = rediscover_details_from_existing_tasks(DB, ROOT / "data" / "snapshots", ROOT)
        progress.progress(100)
        after_df = analyzed_tasks()
        after = quality_snapshot(after_df)
        DB.log_run(
            "ui_rediscover_details",
            "saved_high_value_pages",
            "ok" if result.success_count else "blocked",
            "; ".join(result.failures),
            result.success_count,
            result.failure_count,
            result.new_count,
            result.updated_count,
        )
        st.session_state["last_reparse_compare"] = {"before": before, "after": after}
        st.session_state["last_online_collect"] = {
            "entry_page_count": 0,
            "candidate_count": result.candidate_count,
            "written_count": result.written_count,
            "filtered_count": result.filtered_count,
            "failure_count": result.failure_count,
            "new_count": result.new_count,
            "updated_count": result.updated_count,
            "quality": result.quality,
            "failures": result.failures,
        }
        status.success("详情追踪完成。")
        st.rerun()

    st.markdown("**种子详情页采集**")
    stored_seed_urls = load_seed_urls()
    new_seed_url = st.text_input("新增种子 URL", placeholder="https://www.taptap.cn/moment/...")
    if st.button("加入种子列表", width="stretch"):
        urls = stored_seed_urls + ([new_seed_url.strip()] if new_seed_url.strip() else [])
        save_seed_urls(urls)
        st.success("已更新种子列表。")
        st.rerun()
    seed_mode = st.radio("种子池", ["当前有效种子优先", "全部历史种子"], horizontal=True)
    active_only = st.checkbox("只采集有效期任务", value=True, key="seed_collect_active_only")
    default_pool = [url for _, _, url in DEFAULT_CURRENT_DETAIL_SEEDS] if seed_mode == "当前有效种子优先" else stored_seed_urls
    seed_text = st.text_area("固定种子 URL，每行一个", value="\n".join(default_pool), height=150)
    seed_urls = [line.strip() for line in seed_text.splitlines() if line.strip()]
    st.dataframe(display_df(seed_status_table(analyzed_tasks(), seed_urls)), width="stretch", hide_index=True)
    col_seed_collect, col_seed_similar = st.columns(2)
    if col_seed_collect.button("一键采集种子详情页", width="stretch"):
        before_df = analyzed_tasks()
        before = quality_snapshot(before_df)
        save_seed_urls(seed_urls)
        seeds = [(f"ui_seed_{idx + 1}", None, url) for idx, url in enumerate(seed_urls)]
        status.write("正在采集种子详情页...")
        progress.progress(25)
        result = collect_detail_seed_urls(DB, seeds, ROOT / "data" / "snapshots", pause_seconds=0.5, active_only=active_only)
        progress.progress(100)
        after_df = analyzed_tasks()
        after = quality_snapshot(after_df)
        DB.log_run(
            "ui_detail_seed_collect",
            ",".join(seed_urls),
            "ok" if result.success_count else "blocked",
            "; ".join(result.failures),
            result.success_count,
            result.failure_count,
            result.new_count,
            result.updated_count,
        )
        st.session_state["last_reparse_compare"] = {"before": before, "after": after}
        st.session_state["last_online_collect"] = {
            "entry_page_count": result.entry_page_count,
            "candidate_count": result.candidate_count,
            "written_count": result.written_count,
            "filtered_count": result.filtered_count,
            "failure_count": result.failure_count,
            "new_count": result.new_count,
            "updated_count": result.updated_count,
            "quality": result.quality,
            "failures": result.failures,
        }
        status.success("种子详情页采集完成。")
        st.rerun()
    if col_seed_similar.button("一键发现同类详情页", width="stretch"):
        before_df = analyzed_tasks()
        before = quality_snapshot(before_df)
        status.write("正在从已成功 TapTap 详情页发现同类活动...")
        progress.progress(25)
        result = discover_similar_detail_pages(DB, ROOT / "data" / "snapshots", ROOT, pause_seconds=0.5, active_only=active_only)
        progress.progress(100)
        after_df = analyzed_tasks()
        after = quality_snapshot(after_df)
        DB.log_run(
            "ui_similar_detail_discover",
            "saved_taptap_detail_pages",
            "ok" if result.success_count else "blocked",
            "; ".join(result.failures),
            result.success_count,
            result.failure_count,
            result.new_count,
            result.updated_count,
        )
        st.session_state["last_reparse_compare"] = {"before": before, "after": after}
        st.session_state["last_online_collect"] = {
            "entry_page_count": result.entry_page_count,
            "candidate_count": result.candidate_count,
            "written_count": result.written_count,
            "filtered_count": result.filtered_count,
            "failure_count": result.failure_count,
            "new_count": result.new_count,
            "updated_count": result.updated_count,
            "quality": result.quality,
            "failures": result.failures,
        }
        status.success("同类详情页发现完成。")
        st.rerun()

    summary = st.session_state.get("last_online_collect", {})
    current = analyzed_tasks()
    quality = summary.get("quality", {})
    metric_cols = st.columns(6)
    metric_cols[0].metric("入口页数量", summary.get("entry_page_count", 0))
    metric_cols[1].metric("候选详情页数量", summary.get("candidate_count", 0))
    metric_cols[2].metric("写入任务数量", summary.get("written_count", 0))
    metric_cols[3].metric("过滤数量", summary.get("filtered_count", 0))
    metric_cols[4].metric("失败数量", summary.get("failure_count", 0))
    metric_cols[5].metric("字段完整率", quality.get("field_completeness", round(float(current["完整度"].mean()), 2) if not current.empty else 0.0))
    platform_quality = quality.get("platform_completeness", {})
    compare = st.session_state.get("last_reparse_compare")
    if compare:
        st.markdown("**重新解析前后对比**")
        st.dataframe(pd.DataFrame([{"指标": key, "解析前": compare["before"].get(key), "解析后": compare["after"].get(key)} for key in compare["after"]]), width="stretch", hide_index=True)
    st.markdown("**各平台字段完整率**")
    if platform_quality:
        st.dataframe(pd.DataFrame([{"平台": k, "字段完整率": v} for k, v in platform_quality.items()]), width="stretch", hide_index=True)
    else:
        st.info("暂无平台完整率数据，运行网上采集后会生成。")
    logs = DB.df("crawl_runs")
    st.markdown("**最近采集日志**")
    if logs.empty:
        st.info("暂无采集记录")
    else:
        st.dataframe(display_df(logs.tail(8)), width="stretch", hide_index=True)
    st.markdown("**失败原因**")
    if summary.get("failures"):
        st.dataframe(pd.DataFrame({"失败原因": summary["failures"]}), width="stretch", hide_index=True)
    else:
        st.info("暂无失败原因。")
    report = {
        "entry_page_count": summary.get("entry_page_count", 0),
        "candidate_count": summary.get("candidate_count", 0),
        "written_count": summary.get("written_count", 0),
        "filtered_count": summary.get("filtered_count", 0),
        "failure_count": summary.get("failure_count", 0),
        "quality": quality,
    }
    json_bytes, excel_bytes = dataframe_downloads(current, report)
    col1, col2 = st.columns(2)
    col1.download_button("下载采集报告 JSON", json_bytes, file_name="collect_report.json", mime="application/json", width="stretch")
    col2.download_button("下载采集报告 Excel", excel_bytes, file_name="collect_report.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")

with tabs[3]:
    st.subheader("高价值待确认")
    high_value = df[df.get("高价值待确认", False) == True] if not df.empty else df
    if high_value.empty:
        st.info("暂无高价值待确认任务。")
    else:
        table = high_value.copy()
        table["来源"] = table["source_url"]
        table["标题"] = table["task_name"].apply(display_value)
        table["命中的价值关键词"] = table["value_keywords"].apply(display_value)
        table["缺失字段"] = table["未获取字段"].apply(display_value)
        table["可能的详情链接"] = table["candidate_links"].apply(display_value)
        table["图片/海报路径"] = table["image_paths"].apply(display_value)
        st.dataframe(
            display_df(table[["来源", "标题", "命中的价值关键词", "缺失字段", "可能的详情链接", "图片/海报路径"]]),
            width="stretch",
            hide_index=True,
            column_config={"来源": st.column_config.LinkColumn("来源", display_text="打开")},
        )
        col_a, col_b = st.columns(2)
        if col_a.button("重新采集高价值详情", width="stretch"):
            result = rediscover_details_from_existing_tasks(DB, ROOT / "data" / "snapshots", ROOT)
            DB.log_run("ui_high_value_rediscover", "saved_high_value_pages", "ok" if result.success_count else "blocked", "; ".join(result.failures), result.success_count, result.failure_count, result.new_count, result.updated_count)
            st.success(f"完成：写入 {result.written_count} 条，失败 {result.failure_count} 条。")
            st.rerun()
        if col_b.button("重新 OCR", width="stretch"):
            result = reparse_saved_snapshots(DB, ROOT)
            DB.log_run("ui_high_value_reocr", "saved_snapshots", "ok" if result.success_count else "blocked", "; ".join(result.failures), result.success_count, result.failure_count, 0, result.updated_count)
            st.success(f"完成：更新 {result.updated_count} 条，失败 {result.failure_count} 条。")
            st.rerun()
        for idx, row in high_value.head(30).iterrows():
            with st.expander(f"{display_value(row.get('platform'))} / {display_value(row.get('task_name'))}", expanded=False):
                task_detail(row.to_dict(), f"high-value-{idx}")

with tabs[4]:
    st.subheader("扩展情报")
    raw_tasks = DB.df("tasks")
    intel_sources = load_intel_sources(ROOT / "config" / "intel_sources.yaml")
    source_labels = [f"{item['source_name']}（{item['collect_method']}）" for item in intel_sources]
    source_by_label = dict(zip(source_labels, intel_sources))

    st.markdown("**默认采集源配置**")
    st.dataframe(display_df(pd.DataFrame(intel_sources)), width="stretch", hide_index=True)

    template = extension_excel_template()
    st.download_button(
        "下载扩展情报导入模板",
        data=excel_template_bytes(template),
        file_name="extended_intel_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )

    col_demo, col_status = st.columns([1, 2])
    with col_demo:
        if st.button("写入 sample/demo 示例数据", width="stretch"):
            insert_demo_intel(DB)
            st.success("已写入 sample/demo 示例数据；使用 sample/demo 任务键隔离，不参与正式任务判断。")
            st.rerun()
    with col_status:
        selected_status = st.selectbox("扩展情报状态筛选", ["全部"] + INTEL_STATUS_OPTIONS)

    if raw_tasks.empty:
        task_options = {"不关联任务": None}
        st.info("暂无任务。可以先保存为未关联线索。")
    else:
        task_options = {"不关联任务": None}
        task_options.update({f"{row['platform']} / {row['task_name']}": row["dedupe_key"] for _, row in raw_tasks.iterrows()})
    selected_label = st.selectbox("选择任务", list(task_options.keys()))
    task_key = task_options[selected_label]

    st.markdown("**半自动链接解析**")
    source_label = st.selectbox("情报来源", source_labels, key="intel_link_source")
    intel_type_link = st.selectbox("链接数据类型", ["待识别", "游戏热度", "榜单表现", "买量投放", "同类爆款样本", "素材包", "风险信号"])
    intel_url = st.text_input("粘贴情报链接")
    col_preview, col_clear = st.columns([2, 1])
    if col_preview.button("抓取并生成字段预览", width="stretch"):
        if not intel_url:
            st.warning("请先粘贴公开链接。")
        else:
            try:
                html = fetch_public_page(intel_url)
                title = html_title(html)
                text = f"{title or ''}\n{clean_text(html)}"
                fields = extract_opportunity_fields(text, intel_url)
                snapshot_path = save_snapshot(ROOT / "data" / "snapshots" / "intel", "intel_link", html)
                st.session_state["intel_preview"] = {
                    "url": intel_url,
                    "html": html,
                    "title": title,
                    "summary": page_summary(html),
                    "fields": fields,
                    "snapshot_path": snapshot_path,
                    "source_platform": source_by_label[source_label].get("platform"),
                    "intel_type": intel_type_link,
                }
                st.rerun()
            except Exception as exc:
                st.error(f"抓取失败：{exc}")
    if col_clear.button("清空预览", width="stretch"):
        st.session_state.pop("intel_preview", None)
        st.rerun()

    preview = st.session_state.get("intel_preview")
    if preview:
        fields = preview["fields"]
        st.markdown("**字段提取预览**")
        with st.form("intel_preview_confirm_form"):
            edited = {
                **fields,
                "source_url": preview["url"],
                "source_platform": st.text_input("来源平台", value=fields.get("source_platform") or preview.get("source_platform") or ""),
                "task_name": st.text_input("任务名称", value=fields.get("task_name") or ""),
                "game_name": st.text_input("游戏名", value=fields.get("game_name") or ""),
                "reward_summary": st.text_area("奖励/收益", value=fields.get("reward_summary") or ""),
                "deadline": st.text_input("截止时间", value=fields.get("deadline") or ""),
                "entry_requirements": st.text_area("报名门槛", value=fields.get("entry_requirements") or ""),
                "material_requirements": st.text_area("素材要求", value=fields.get("material_requirements") or ""),
                "production_requirements": st.text_area("制作要求", value=fields.get("production_requirements") or ""),
                "risk_keywords": st.text_input("风险关键词", value=fields.get("risk_keywords") or ""),
                "risk_level": st.selectbox("风险等级", ["未知", "低", "中", "高"], index=["未知", "低", "中", "高"].index(fields.get("risk_level") if fields.get("risk_level") in ["未知", "低", "中", "高"] else "未知")),
                "raw_text_excerpt": fields.get("raw_text_excerpt"),
            }
            confirm_status = st.selectbox("保存状态", ["待确认", "已确认"], index=0)
            submitted_preview = st.form_submit_button("确认保存字段")
            if submitted_preview:
                if task_key:
                    record = save_pending_intel_link(
                        DB,
                        task_dedupe_key=task_key,
                        source_url=preview["url"],
                        source_platform=edited.get("source_platform"),
                        intel_type=preview.get("intel_type") or "待识别",
                        snapshot_dir=ROOT / "data" / "snapshots" / "intel",
                        fetcher=lambda url: preview["html"],
                        extracted_fields=edited,
                    )
                    record["intel_status"] = confirm_status
                    DB.upsert_latest_record("opportunity_intel_links", ["task_dedupe_key", "source_url"], record)
                    persist_extracted_extensions(task_key, edited)
                    st.success("已保存到当前任务的扩展情报线索。")
                else:
                    save_unlinked_intel(
                        DB,
                        source_url=preview["url"],
                        page_title=preview.get("title"),
                        page_summary=preview.get("summary"),
                        snapshot_path=preview.get("snapshot_path"),
                        source_platform=edited.get("source_platform"),
                        fields=edited,
                        intel_status=confirm_status,
                    )
                    st.success("已保存为未关联线索。")
                st.session_state.pop("intel_preview", None)
                st.rerun()
        if source_url_exists(preview["url"]):
            st.warning("该来源链接已经存在于任务库，不会重复创建推广任务。")
        else:
            hint = similar_task_hint(fields)
            if hint:
                st.warning(hint)
            if st.button("根据该线索创建推广任务", width="stretch"):
                task = task_from_extracted_fields(fields, preview.get("snapshot_path"))
                DB.upsert_tasks([task])
                persist_extracted_extensions(task.dedupe_key(), fields)
                st.success("已根据线索创建推广任务。")
                st.rerun()

    if task_key is None:
        st.info("选择具体任务后，可以继续手动新增热度、榜单、买量、样本、素材和风险数据。")

    else:
        st.markdown("**新增数据**")
        entry_type = st.selectbox("情报类型", ["游戏热度", "榜单表现", "买量投放", "同类爆款样本", "素材包", "风险信号"])
        with st.form("extended_intel_form"):
            intel_status = st.selectbox("状态", INTEL_STATUS_OPTIONS, index=1)
            if entry_type == "游戏热度":
                game_search_keyword = st.text_input("游戏搜索关键词")
                heat_source = st.text_input("热度来源")
                heat_index = st.number_input("热度指数", value=0.0)
                heat_trend = st.selectbox("热度趋势", ["上升", "平稳", "下降", "未知"])
                heat_source_url = st.text_input("热度来源链接")
                heat_notes = st.text_area("备注")
                submitted = st.form_submit_button("保存")
                if submitted:
                    DB.insert_record("opportunity_heat_metrics", locals() | {"task_dedupe_key": task_key})
                    st.success("已保存热度数据。")
            elif entry_type == "榜单表现":
                app_rank_source = st.text_input("榜单来源")
                app_store_platform = st.selectbox("应用商店平台", ["App Store", "安卓市场", "TapTap", "其他"])
                app_rank_category = st.text_input("榜单分类")
                app_rank_position = st.number_input("当前排名", value=0, step=1)
                app_rank_change = st.number_input("排名变化", value=0, step=1)
                app_rank_source_url = st.text_input("榜单来源链接")
                submitted = st.form_submit_button("保存")
                if submitted:
                    DB.insert_record("opportunity_app_ranks", locals() | {"task_dedupe_key": task_key})
                    st.success("已保存榜单数据。")
            elif entry_type == "买量投放":
                ad_intel_source = st.text_input("买量数据来源")
                ad_material_count = st.number_input("投放素材数量", value=0, step=1)
                ad_platforms = st.text_input("投放平台")
                ad_trend = st.selectbox("投放趋势", ["增强", "平稳", "减弱", "未知"])
                ad_source_url = st.text_input("来源链接")
                submitted = st.form_submit_button("保存")
                if submitted:
                    DB.insert_record("opportunity_ad_intel", locals() | {"task_dedupe_key": task_key})
                    st.success("已保存买量数据。")
            elif entry_type == "同类爆款样本":
                sample_platform = st.selectbox("样本平台", ["抖音", "快手", "B站", "小红书", "视频号", "其他"])
                sample_keyword = st.text_input("搜索关键词")
                sample_video_title = st.text_input("视频标题")
                sample_like_count = st.number_input("点赞数", value=0, step=1)
                sample_comment_count = st.number_input("评论数", value=0, step=1)
                sample_content_type = st.selectbox("内容类型", ["试玩录屏", "攻略讲解", "福利情报", "混剪二创", "口播推荐", "实况挑战", "其他"])
                sample_source_url = st.text_input("视频链接")
                submitted = st.form_submit_button("保存")
                if submitted:
                    DB.upsert_sample_video(locals() | {"task_dedupe_key": task_key})
                    st.success("已保存样本视频。")
            elif entry_type == "素材包":
                material_pack_url = st.text_input("素材包链接")
                has_official_material = st.checkbox("有官方素材")
                has_video_material = st.checkbox("有视频素材")
                has_script_template = st.checkbox("有脚本模板")
                material_download_status = st.selectbox("下载状态", ["未下载", "已下载", "下载失败", "无需下载"])
                material_notes = st.text_area("素材备注")
                submitted = st.form_submit_button("保存")
                if submitted:
                    material_key = material_pack_url or f"manual://material/{task_key}"
                    DB.upsert_latest_record(
                        "opportunity_material_assets",
                        ["task_dedupe_key", "material_pack_url"],
                        locals() | {"task_dedupe_key": task_key, "material_pack_url": material_key},
                    )
                    st.success("已保存素材包数据。")
            else:
                risk_level = st.selectbox("综合风险等级", ["低", "中", "高", "未知"])
                copyright_risk = st.selectbox("版权风险", ["低", "中", "高", "未知"])
                settlement_risk = st.selectbox("结算风险", ["低", "中", "高", "未知"])
                content_risk = st.selectbox("内容违规风险", ["低", "中", "高", "未知"])
                risk_keywords = st.text_input("风险关键词")
                risk_notes = st.text_area("风险备注")
                submitted = st.form_submit_button("保存")
                if submitted:
                    DB.upsert_latest_record("opportunity_risk_signals", ["task_dedupe_key"], locals() | {"task_dedupe_key": task_key})
                    st.success("已保存风险数据。")
    st.markdown("**已录入扩展情报表**")
    counts = []
    for table_name in [
        "opportunity_heat_metrics",
        "opportunity_app_ranks",
        "opportunity_ad_intel",
        "opportunity_sample_videos",
        "opportunity_material_assets",
        "opportunity_risk_signals",
        "opportunity_intel_links",
        "opportunity_unlinked_intel",
    ]:
        table = status_filter(DB.df(table_name), selected_status)
        counts.append({"表": table_name, "记录数": len(table)})
    st.dataframe(pd.DataFrame(counts), width="stretch", hide_index=True)
    pending = status_filter(DB.df("opportunity_intel_links"), "待确认")
    if pending.empty:
        st.info("暂无待确认链接。")
    else:
        st.markdown("**待确认链接**")
        st.dataframe(
            display_df(pending[["source_platform", "intel_type", "page_title", "source_url", "snapshot_path", "intel_status", "updated_at"]]),
            width="stretch",
            hide_index=True,
            column_config={"source_url": st.column_config.LinkColumn("source_url", display_text="打开")},
        )
    unlinked = DB.df("opportunity_unlinked_intel")
    unlinked = status_filter(unlinked, selected_status)
    st.markdown("**未关联线索列表**")
    if unlinked.empty:
        st.info("暂无未关联线索。")
    else:
        st.dataframe(
            display_df(unlinked[["source_platform", "page_title", "extracted_game_name", "extracted_reward", "extracted_deadline", "source_url", "intel_status"]]),
            width="stretch",
            hide_index=True,
            column_config={"source_url": st.column_config.LinkColumn("source_url", display_text="打开")},
        )
        active_unlinked = unlinked[unlinked["intel_status"].fillna("待确认") != "已忽略"]
        if not active_unlinked.empty:
            clue_options = {
                f"{display_value(row.get('source_platform'))} / {display_value(row.get('page_title'))}": row.to_dict()
                for _, row in active_unlinked.iterrows()
            }
            selected_clue_label = st.selectbox("选择未关联线索", list(clue_options.keys()))
            selected_clue = clue_options[selected_clue_label]
            task_targets = {label: key for label, key in task_options.items() if key}
            col_link, col_create, col_ignore = st.columns(3)
            with col_link:
                if task_targets:
                    target_label = st.selectbox("关联到任务", list(task_targets.keys()))
                    if st.button("关联已有任务", width="stretch"):
                        link_unlinked_intel(DB, selected_clue["source_url"], task_targets[target_label])
                        st.success("已关联到任务。")
                        st.rerun()
            with col_create:
                if st.button("根据该线索创建推广任务", key="create_from_unlinked", width="stretch"):
                    import json

                    fields = json.loads(selected_clue.get("extracted_fields_json") or "{}")
                    fields.setdefault("source_url", selected_clue.get("source_url"))
                    fields.setdefault("source_platform", selected_clue.get("source_platform"))
                    if source_url_exists(str(fields.get("source_url") or "")):
                        st.warning("该来源链接已存在，不重复创建。")
                    else:
                        task = task_from_extracted_fields(fields, selected_clue.get("snapshot_path"))
                        DB.upsert_tasks([task])
                        persist_extracted_extensions(task.dedupe_key(), fields)
                        link_unlinked_intel(DB, selected_clue["source_url"], task.dedupe_key())
                        st.success("已创建推广任务并关联线索。")
                        st.rerun()
            with col_ignore:
                if st.button("忽略线索", width="stretch"):
                    from game_promo_radar.intel import ignore_unlinked_intel

                    ignore_unlinked_intel(DB, selected_clue["source_url"])
                    st.success("已忽略。")
                    st.rerun()

with tabs[5]:
    st.subheader("历史任务 / 已截止")
    history = df[df["生命周期"] == "已截止"] if not df.empty else df
    if history.empty:
        st.info("暂无已截止历史任务。")
    else:
        st.dataframe(
            display_df(core_table(history.sort_values("deadline", ascending=False))),
            width="stretch",
            hide_index=True,
            column_config=source_link_column_config(),
        )
        for idx, row in history.head(40).iterrows():
            with st.expander(f"{display_value(row.get('platform'))} / {display_value(row.get('task_name'))}", expanded=False):
                task_detail(row.to_dict(), f"history-{idx}")

with tabs[6]:
    st.subheader("截止提醒")
    reminders = df[df["生命周期"].isin(["即将截止"])] if not df.empty else df
    if reminders.empty:
        st.info("暂无即将截止且仍可投稿的任务。")
    else:
        for idx, row in reminders.iterrows():
            task_card(row.to_dict(), f"deadline-{idx}")

with tabs[7]:
    st.subheader("热度分析")
    keyword = st.text_input("游戏关键词")
    if st.button("分析公开作品热度"):
        result = MediaCrawlerAdapter().analyze_keyword(keyword)
        st.json(result)
        st.warning("MediaCrawler 尚未配置。未获取到的热度和竞争数据不会被猜测。")

with tabs[8]:
    st.subheader("导入导出")
    with st.form("manual_url"):
        platform = st.selectbox("平台", ["抖音", "快手", "B站", "TapTap", "其他"])
        game_name = st.text_input("游戏名称")
        task_name = st.text_input("任务名称")
        source_url = st.text_input("来源链接")
        task_type = st.selectbox("任务类型", ["CPM", "CPA", "CPS", "CPT", "奖金活动", "普通创作激励"])
        unit_price = st.text_input("单价，未知留空")
        revenue_share = st.text_input("分成比例，未知留空")
        deadline = st.text_input("截止时间，例如 2026-07-31，未知留空")
        account_requirements = st.text_area("报名门槛，未知留空")
        material_url = st.text_input("素材链接，未知留空")
        production_requirements = st.text_area("制作要求，未知留空")
        signup_url = st.text_input("报名入口，未知留空")
        if st.form_submit_button("保存手动任务"):
            task = task_from_row(
                {
                    "platform": platform,
                    "game_name": game_name or None,
                    "task_name": task_name or "手动导入任务",
                    "source_url": source_url or "manual://link",
                    "task_type": task_type,
                    "unit_price": unit_price or None,
                    "revenue_share": revenue_share or None,
                    "deadline": deadline or None,
                    "account_requirements": account_requirements or None,
                    "material_url": material_url or None,
                    "production_requirements": production_requirements or None,
                    "signup_url": signup_url or None,
                }
            )
            DB.upsert_tasks([task])
            st.success("已保存。")
    uploaded = st.file_uploader("导入 Excel", type=["xlsx"])
    if uploaded:
        tmp = ROOT / "data" / "manual_import.xlsx"
        tmp.write_bytes(uploaded.getvalue())
        imported = import_excel(tmp)
        DB.upsert_tasks(imported)
        import_extended_excel_rows(pd.read_excel(tmp), imported)
        st.success(f"已导入 {len(imported)} 条。")
    if not df.empty and st.button("导出 Excel"):
        out = ROOT / "data" / "exports" / "tasks_with_analysis.xlsx"
        export_excel(df, out)
        st.success(f"已导出：{out}")

with tabs[9]:
    st.subheader("数据源")
    cfg = sources_config()
    st.dataframe(display_df(pd.DataFrame(cfg["sources"])), width="stretch", hide_index=True)
    phase1 = {s["key"]: s for s in cfg["sources"] if s.get("phase") == 1}
    col1, col2 = st.columns(2)
    with col1:
        if st.button("采集抖音公开页面"):
            source = phase1["douyin_game_publisher"]
            result = DouyinGamePublisherAdapter(source["public_urls"], ROOT / "data" / "snapshots").collect()
            DB.upsert_tasks(result.tasks)
            DB.log_run(source["key"], ",".join(source["public_urls"]), result.status, result.message, len(result.tasks), 0, 0, 0)
            st.success(f"采集完成：{len(result.tasks)} 条。")
    with col2:
        if st.button("采集快手星火公开页面"):
            source = phase1["kuaishou_spark"]
            result = KuaishouSparkAdapter(source["public_urls"], ROOT / "data" / "snapshots").collect()
            DB.upsert_tasks(result.tasks)
            DB.log_run(source["key"], ",".join(source["public_urls"]), result.status, result.message, len(result.tasks), 0, 0, 0)
            st.success(f"采集完成：{len(result.tasks)} 条。")

with tabs[10]:
    st.subheader("结果备注")
    raw = DB.df("tasks")
    if raw.empty:
        st.info("暂无任务。")
    else:
        with st.form("task_note"):
            selected = st.selectbox("任务", raw["dedupe_key"].tolist())
            note = st.text_area("人工备注", placeholder="例如：已报名、已发布、最终效果、结算备注等")
            if st.form_submit_button("保存备注"):
                DB.add_task_note(TaskNote(selected, note))
                st.success("已保存备注。")
    st.dataframe(display_df(DB.df("task_notes")), width="stretch", hide_index=True)

with tabs[11]:
    st.subheader("运行日志")
    auto_config = load_auto_config(AUTO_CONFIG_PATH)
    auto_runs = load_auto_runs(AUTO_RUNS_PATH)
    col1, col2, col3 = st.columns(3)
    col1.metric("自动采集", "启用" if auto_config.enabled else "停用")
    next_time = next_collect_time(auto_config)
    col2.metric("下一次采集时间", display_value(next_time.replace(microsecond=0).isoformat() if next_time else None))
    col3.metric("最近自动采集", display_value(auto_runs[-1].get("created_at") if auto_runs else None))
    if auto_runs:
        latest = auto_runs[-1]
        col4, col5, col6 = st.columns(3)
        col4.metric("本次新增任务数", latest.get("new_count", 0))
        col5.metric("本次推荐做", latest.get("recommended_count", 0))
        col6.metric("本次可以做", latest.get("doable_count", 0))
    logs = DB.df("crawl_runs")
    if logs.empty:
        st.info("暂无采集记录")
    else:
        st.dataframe(display_df(logs), width="stretch", hide_index=True)


from __future__ import annotations

from pathlib import Path
from difflib import SequenceMatcher
import sys

import pandas as pd
import streamlit as st
import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

from game_promo_radar.analysis import analyze_task
from game_promo_radar.adapters.manual import export_excel, import_excel, preview_excel, task_from_row
from game_promo_radar.adapters.mediacrawler import MediaCrawlerAdapter
from game_promo_radar.adapters.public_web import DouyinGamePublisherAdapter, KuaishouSparkAdapter, collect_public_web_candidates
from game_promo_radar.db import RadarDB
from game_promo_radar.models import AccountProfile, DataSource, ImportRun, TaskNote
from game_promo_radar.rules import deadline_status, display_value

DB = RadarDB(ROOT / "data" / "game_promo_radar.duckdb")

LABELS = {
    "title": "内容推广商机雷达",
    "caption": "个人本地公开情报工具：发现推广商机，判断是否值得做、适合什么账号做、制作难度和结算风险。",
    "tabs": ["今日新增商机", "任务库", "任务详情", "账号画像", "截止提醒", "热度分析", "导入导出", "数据源", "结算记录", "采集/导入记录"],
    "platform": "\u5e73\u53f0",
    "game": "任务对象",
    "task": "\u4efb\u52a1\u540d\u79f0",
    "category": "任务分类",
    "settlement": "结算方式",
    "content_form": "作品形式",
    "target_account": "适合账号",
    "publish_platforms": "可发布平台",
    "reward_rule": "结算规则",
    "risk": "风险等级",
    "difficulty_level": "难度等级",
    "expected_value": "预估价值",
    "account_match": "账号匹配",
    "is_game_related": "游戏相关",
    "worth_doing": "是否值得做",
    "type": "\u4efb\u52a1\u7c7b\u578b",
    "billing": "\u8ba1\u8d39\u65b9\u5f0f",
    "price": "\u5355\u4ef7",
    "share": "\u5206\u6210\u6bd4\u4f8b",
    "reward": "\u5956\u52b1",
    "deadline": "\u622a\u6b62\u65f6\u95f4",
    "requirement": "\u62a5\u540d\u95e8\u69db",
    "material": "\u7d20\u6750",
    "production": "\u5236\u4f5c\u8981\u6c42",
    "signup": "\u62a5\u540d\u5165\u53e3",
    "source": "\u6765\u6e90\u94fe\u63a5",
    "snapshot": "\u539f\u59cb\u5feb\u7167",
    "updated": "\u6700\u540e\u66f4\u65b0",
    "feasibility": "\u53ef\u505a\u6027",
    "difficulty": "\u5236\u4f5c\u96be\u5ea6",
    "evidence": "\u5224\u65ad\u4f9d\u636e",
    "missing": "\u672a\u83b7\u53d6\u5b57\u6bb5",
    "deadline_status": "\u622a\u6b62\u72b6\u6001",
}

CATEGORY_OPTIONS = {
    "game": "游戏推广",
    "app": "App 推广",
    "ecommerce": "电商种草",
    "local_life": "本地生活",
    "short_drama": "影视短剧",
    "brand": "品牌活动",
    "platform_incentive": "平台激励",
    "other": "其他",
}
SETTLEMENT_OPTIONS = {
    "play_count": "播放量",
    "interaction": "互动量",
    "download": "下载/注册",
    "lead": "线索",
    "sale_commission": "成交佣金",
    "fixed_reward": "固定奖励",
    "traffic_support": "流量扶持",
    "unknown": "未知",
}
CONTENT_FORM_OPTIONS = {
    "short_video": "短视频",
    "note": "图文笔记",
    "live": "直播",
    "image_text": "图片文字",
    "mixed": "混合",
}
RISK_OPTIONS = {"low": "低", "medium": "中", "high": "高"}
SOURCE_PLATFORMS = ["抖音", "快手", "小红书", "B站", "品牌官网", "手动链接", "Excel", "截图 OCR"]
COLLECTION_METHODS = ["public_web", "manual_link", "excel", "ocr", "creator_center", "placeholder"]


def duplicate_hint(candidate: dict, existing: pd.DataFrame) -> str:
    if existing.empty:
        return ""
    source_url = str(candidate.get("source_url") or "")
    platform = str(candidate.get("platform") or "")
    title = str(candidate.get("task_name") or "")
    reward = str(candidate.get("reward_rule_text") or "")
    if source_url and not existing[existing["source_url"].astype(str) == source_url].empty:
        return "同一链接已存在，将更新原任务"
    for row in existing.to_dict("records"):
        if str(row.get("platform") or "") != platform:
            continue
        title_ratio = SequenceMatcher(None, title, str(row.get("task_name") or "")).ratio()
        reward_ratio = SequenceMatcher(None, reward, str(row.get("reward_rule_text") or "")).ratio() if reward else 0
        if title_ratio >= 0.82 and (not reward or reward_ratio >= 0.72):
            return "疑似重复：标题相似且平台相同"
    return ""


def sources_config() -> dict:
    with open(ROOT / "config" / "sources.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def raw_tasks() -> pd.DataFrame:
    return DB.df("tasks")


def account_profiles() -> pd.DataFrame:
    return DB.df("account_profiles")


def analyzed_tasks(account_profile: dict | None = None) -> pd.DataFrame:
    df = raw_tasks()
    if df.empty:
        return df
    rows = []
    for task in df.to_dict("records"):
        result = analyze_task(task, account_profile=account_profile)
        rows.append(
            {
                **task,
                LABELS["feasibility"]: result.feasibility,
                LABELS["difficulty"]: result.difficulty,
                LABELS["risk"]: RISK_OPTIONS.get(result.risk_level, result.risk_level),
                LABELS["expected_value"]: result.expected_value_score,
                LABELS["account_match"]: result.account_match_score,
                LABELS["target_account"]: result.suitable_account_type,
                LABELS["worth_doing"]: "是" if result.worth_doing else "否",
                LABELS["evidence"]: "\n".join(result.evidence),
                LABELS["missing"]: "\u3001".join(result.missing_fields) if result.missing_fields else "",
                LABELS["deadline_status"]: deadline_status(task.get("deadline")),
            }
        )
    return pd.DataFrame(rows)


def display_tasks(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    shown = df.astype("object").copy()
    for col in shown.columns:
        shown[col] = shown[col].apply(display_value)
    return shown.astype(str)


def rename_task_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(
        columns={
            "platform": LABELS["platform"],
            "game_name": LABELS["game"],
            "task_name": LABELS["task"],
            "task_category": LABELS["category"],
            "settlement_type": LABELS["settlement"],
            "content_form": LABELS["content_form"],
            "publish_platforms": LABELS["publish_platforms"],
            "reward_rule_text": LABELS["reward_rule"],
            "difficulty_level": LABELS["difficulty_level"],
            "is_game_related": LABELS["is_game_related"],
            "task_type": LABELS["type"],
            "billing_method": LABELS["billing"],
            "unit_price": LABELS["price"],
            "revenue_share": LABELS["share"],
            "deadline": LABELS["deadline"],
            "account_requirements": LABELS["requirement"],
            "material_url": LABELS["material"],
            "production_requirements": LABELS["production"],
            "signup_url": LABELS["signup"],
            "source_url": LABELS["source"],
            "raw_snapshot": LABELS["snapshot"],
            "last_updated_at": LABELS["updated"],
        }
    )


st.set_page_config(page_title=LABELS["title"], layout="wide")
st.title(LABELS["title"])
st.caption(LABELS["caption"])

profiles_df = account_profiles()
selected_profile: dict | None = None
if profiles_df.empty:
    st.sidebar.info("未配置账号画像，评分使用通用账号建议。")
else:
    profile_options = profiles_df["profile_key"].tolist()
    selected_key = st.sidebar.selectbox("当前评分账号", profile_options, format_func=lambda key: profiles_df[profiles_df["profile_key"] == key].iloc[0]["account_name"])
    selected_profile = profiles_df[profiles_df["profile_key"] == selected_key].iloc[0].to_dict()

tabs = st.tabs(LABELS["tabs"])

with tabs[0]:
    st.subheader(LABELS["tabs"][0])
    df = analyzed_tasks(selected_profile)
    if df.empty:
        st.info("\u6682\u65e0\u4efb\u52a1\u3002\u8bf7\u5148\u5728\u201c\u6570\u636e\u6e90\u201d\u91c7\u96c6\u6216\u5728\u201c\u5bfc\u5165\u5bfc\u51fa\u201d\u624b\u52a8\u5bfc\u5165\u3002")
    else:
        today = pd.Timestamp.today().date().isoformat()
        metric_cols = st.columns(6)
        metric_cols[0].metric("今日新增商机", int(df["first_seen_at"].astype(str).str.startswith(today).sum()))
        metric_cols[1].metric("高价值任务", int((df[LABELS["expected_value"]] >= 70).sum()))
        metric_cols[2].metric("低风险可做任务", int(((df[LABELS["risk"]] == "低") & (df[LABELS["worth_doing"]] == "是")).sum()))
        metric_cols[3].metric("游戏类任务", int((df["task_category"] == "game").sum()))
        metric_cols[4].metric("非游戏类任务", int((df["task_category"] != "game").sum()))
        metric_cols[5].metric("待人工确认任务", int(df[LABELS["missing"]].astype(str).ne("").sum()))
        view = rename_task_columns(df[df["first_seen_at"].astype(str).str.startswith(today)])
        cols = [
            LABELS["platform"], LABELS["category"], LABELS["game"], LABELS["task"],
            LABELS["worth_doing"], LABELS["expected_value"], LABELS["risk"],
            LABELS["account_match"], LABELS["difficulty"], LABELS["deadline_status"],
            LABELS["evidence"], LABELS["source"],
        ]
        st.dataframe(display_tasks(view[cols]), width="stretch", hide_index=True)

with tabs[1]:
    st.subheader(LABELS["tabs"][1])
    df = analyzed_tasks(selected_profile)
    if df.empty:
        st.info("\u6682\u65e0\u4efb\u52a1\u3002")
    else:
        filters = st.columns(4)
        platform_filter = filters[0].multiselect(LABELS["platform"], sorted(df["platform"].dropna().unique().tolist()))
        category_filter = filters[1].multiselect(LABELS["category"], list(CATEGORY_OPTIONS.keys()), format_func=lambda x: CATEGORY_OPTIONS.get(x, x))
        settlement_filter = filters[2].multiselect(LABELS["settlement"], list(SETTLEMENT_OPTIONS.keys()), format_func=lambda x: SETTLEMENT_OPTIONS.get(x, x))
        risk_filter = filters[3].multiselect(LABELS["risk"], list(RISK_OPTIONS.keys()), format_func=lambda x: RISK_OPTIONS.get(x, x))
        game_only = st.checkbox("只看游戏相关任务", value=False)

        filtered = df.copy()
        if platform_filter:
            filtered = filtered[filtered["platform"].isin(platform_filter)]
        if category_filter:
            filtered = filtered[filtered["task_category"].isin(category_filter)]
        if settlement_filter:
            filtered = filtered[filtered["settlement_type"].isin(settlement_filter)]
        if risk_filter:
            filtered = filtered[filtered[LABELS["risk"]].isin([RISK_OPTIONS.get(x, x) for x in risk_filter])]
        if game_only:
            filtered = filtered[(filtered["task_category"] == "game") | (filtered["is_game_related"] == True)]

        view = rename_task_columns(filtered)
        view[LABELS["reward"]] = view.apply(
            lambda row: row[LABELS["price"]] if not pd.isna(row.get(LABELS["price"])) else row.get(LABELS["share"]),
            axis=1,
        )
        cols = [
            LABELS["platform"], LABELS["category"], LABELS["settlement"], LABELS["content_form"],
            LABELS["game"], LABELS["task"], LABELS["reward"], LABELS["worth_doing"],
            LABELS["feasibility"], LABELS["expected_value"], LABELS["account_match"],
            LABELS["target_account"], LABELS["risk"], LABELS["difficulty"], LABELS["evidence"],
            LABELS["requirement"], LABELS["deadline"], LABELS["deadline_status"],
            LABELS["material"], LABELS["production"], LABELS["reward_rule"],
            LABELS["source"], LABELS["snapshot"], LABELS["updated"],
        ]
        st.dataframe(display_tasks(view[cols]), width="stretch", hide_index=True)

with tabs[2]:
    st.subheader(LABELS["tabs"][2])
    df = analyzed_tasks(selected_profile)
    if df.empty:
        st.info("暂无任务。")
    else:
        task_labels = df.apply(
            lambda row: f"{row['platform']} | {CATEGORY_OPTIONS.get(row['task_category'], row['task_category'])} | {row['task_name']}",
            axis=1,
        ).tolist()
        selected_index = st.selectbox("选择任务", list(range(len(task_labels))), format_func=lambda i: task_labels[i])
        task = df.iloc[selected_index].to_dict()
        result = analyze_task(task, account_profile=selected_profile)

        st.markdown(f"### {task.get('task_name')}")
        meta_cols = st.columns(4)
        meta_cols[0].metric(LABELS["worth_doing"], "是" if result.worth_doing else "否")
        meta_cols[1].metric(LABELS["expected_value"], result.expected_value_score)
        meta_cols[2].metric(LABELS["account_match"], result.account_match_score)
        meta_cols[3].metric(LABELS["risk"], RISK_OPTIONS.get(result.risk_level, result.risk_level))

        detail = {
            LABELS["source"]: task.get("source_url"),
            LABELS["category"]: CATEGORY_OPTIONS.get(task.get("task_category"), task.get("task_category")),
            LABELS["platform"]: task.get("platform"),
            LABELS["settlement"]: SETTLEMENT_OPTIONS.get(task.get("settlement_type"), task.get("settlement_type")),
            LABELS["content_form"]: CONTENT_FORM_OPTIONS.get(task.get("content_form"), task.get("content_form")),
            LABELS["reward_rule"]: task.get("reward_rule_text"),
            LABELS["deadline"]: task.get("deadline"),
            LABELS["requirement"]: task.get("account_requirements"),
            LABELS["production"]: task.get("production_requirements"),
            LABELS["signup"]: task.get("signup_url"),
        }
        st.dataframe(display_tasks(pd.DataFrame([detail])), width="stretch", hide_index=True)

        explain_cols = st.columns(2)
        with explain_cols[0]:
            st.markdown("#### 适合什么账号做")
            st.write(result.suitable_account_type)
            if selected_profile:
                st.write(f"当前账号：{selected_profile.get('account_name')} / {selected_profile.get('account_domain')}")
            st.markdown("#### 风险提示")
            st.write("高风险任务不推荐；涉及刷量、虚假互动、侵权、灰产、诈骗或结算规则严重不确定时应放弃。")
        with explain_cols[1]:
            st.markdown("#### 为什么值得/不值得做")
            for item in result.evidence:
                st.write(f"- {item}")

with tabs[3]:
    st.subheader(LABELS["tabs"][3])
    with st.form("account_profile"):
        account_name = st.text_input("账号名称")
        account_platform = st.selectbox("账号平台", ["抖音", "快手", "小红书", "B站", "TapTap", "其他"])
        account_domain = st.text_input("账号领域", placeholder="例如：游戏,测评,AI工具")
        follower_count = st.number_input("粉丝量", min_value=0, step=100)
        average_views = st.number_input("平均播放", min_value=0, step=100)
        content_forms = st.multiselect("擅长内容形式", list(CONTENT_FORM_OPTIONS.keys()), format_func=lambda x: CONTENT_FORM_OPTIONS.get(x, x))
        real_person = st.checkbox("是否真人出镜")
        acceptable_categories = st.multiselect("可承接分类", list(CATEGORY_OPTIONS.keys()), format_func=lambda x: CATEGORY_OPTIONS.get(x, x))
        if st.form_submit_button("保存账号画像"):
            if not account_name.strip():
                st.error("账号名称不能为空。")
            else:
                DB.upsert_account_profile(
                    AccountProfile(
                        account_name=account_name.strip(),
                        platform=account_platform,
                        account_domain=account_domain.strip() or "待确认",
                        follower_count=int(follower_count),
                        average_views=int(average_views),
                        content_forms=",".join(content_forms),
                        real_person=real_person,
                        acceptable_categories=",".join(acceptable_categories),
                    )
                )
                st.success("已保存账号画像。")
    profiles = account_profiles()
    if profiles.empty:
        st.info("暂无账号画像。")
    else:
        st.dataframe(display_tasks(profiles), width="stretch", hide_index=True)

with tabs[4]:
    st.subheader(LABELS["tabs"][4])
    df = analyzed_tasks(selected_profile)
    if df.empty:
        st.info("\u6682\u65e0\u4efb\u52a1\u3002")
    else:
        reminders = df[df[LABELS["deadline_status"]].isin(["\u5373\u5c06\u622a\u6b62", "\u5df2\u622a\u6b62"])]
        view = rename_task_columns(reminders)
        cols = [LABELS["platform"], LABELS["game"], LABELS["task"], LABELS["deadline"], LABELS["deadline_status"], LABELS["feasibility"], LABELS["difficulty"], LABELS["source"]]
        st.dataframe(display_tasks(view[cols]), width="stretch", hide_index=True)

with tabs[5]:
    st.subheader(LABELS["tabs"][5])
    keyword = st.text_input("推广任务关键词")
    if st.button("\u5206\u6790\u516c\u5f00\u4f5c\u54c1\u70ed\u5ea6"):
        result = MediaCrawlerAdapter().analyze_keyword(keyword)
        st.json(result)
        st.warning("MediaCrawler \u5c1a\u672a\u914d\u7f6e\u3002\u672a\u83b7\u53d6\u5230\u7684\u70ed\u5ea6\u548c\u7ade\u4e89\u6570\u636e\u4e0d\u4f1a\u88ab\u731c\u6d4b\uff0c\u5206\u6790\u4e2d\u663e\u793a\u4e3a\u201c\u5f85\u786e\u8ba4\u201d\u3002")

with tabs[6]:
    st.subheader(LABELS["tabs"][6])
    st.markdown("#### 手动链接导入")
    with st.form("manual_url"):
        platform = st.selectbox(LABELS["platform"], ["抖音", "快手", "小红书", "B站", "TapTap", "品牌官网", "手动链接", "Excel", "截图 OCR", "其他"])
        task_category = st.selectbox(LABELS["category"], list(CATEGORY_OPTIONS.keys()), format_func=lambda x: CATEGORY_OPTIONS.get(x, x))
        settlement_type = st.selectbox(LABELS["settlement"], list(SETTLEMENT_OPTIONS.keys()), format_func=lambda x: SETTLEMENT_OPTIONS.get(x, x))
        content_form = st.selectbox(LABELS["content_form"], list(CONTENT_FORM_OPTIONS.keys()), format_func=lambda x: CONTENT_FORM_OPTIONS.get(x, x))
        game_name = st.text_input(LABELS["game"])
        task_name = st.text_input("标题")
        source_url = st.text_input("任务链接")
        target_account_type = st.text_input(LABELS["target_account"])
        publish_platforms = st.text_input(LABELS["publish_platforms"], placeholder="例如：抖音,小红书,B站")
        reward_rule_text = st.text_area(LABELS["reward_rule"])
        risk_note = st.text_area("风险备注")
        is_game_related = st.checkbox(LABELS["is_game_related"], value=task_category == "game")
        task_type = st.selectbox(LABELS["type"], ["CPM", "CPA", "CPS", "CPT", "\u5956\u91d1\u6d3b\u52a8", "\u666e\u901a\u521b\u4f5c\u6fc0\u52b1"])
        unit_price = st.text_input("\u5355\u4ef7\uff0c\u672a\u77e5\u7559\u7a7a")
        revenue_share = st.text_input("\u5206\u6210\u6bd4\u4f8b\uff0c\u672a\u77e5\u7559\u7a7a")
        deadline = st.text_input("\u622a\u6b62\u65f6\u95f4\uff0c\u4f8b\u5982 2026-07-31\uff0c\u672a\u77e5\u7559\u7a7a")
        account_requirements = st.text_area("\u62a5\u540d\u95e8\u69db\uff0c\u672a\u77e5\u7559\u7a7a")
        material_url = st.text_input("\u7d20\u6750\u94fe\u63a5\uff0c\u672a\u77e5\u7559\u7a7a")
        production_requirements = st.text_area("\u5236\u4f5c\u8981\u6c42\uff0c\u672a\u77e5\u7559\u7a7a")
        signup_url = st.text_input("\u62a5\u540d\u5165\u53e3\uff0c\u672a\u77e5\u7559\u7a7a")
        if st.form_submit_button("\u4fdd\u5b58\u624b\u52a8\u4efb\u52a1"):
            if not source_url.strip():
                st.error("任务链接不能为空。")
            else:
                task = task_from_row(
                    {
                        "platform": platform,
                        "task_category": task_category,
                        "settlement_type": settlement_type,
                        "content_form": content_form,
                        "game_name": game_name or "\u5f85\u786e\u8ba4",
                        "task_name": task_name or "\u624b\u52a8\u5bfc\u5165\u4efb\u52a1",
                        "source_url": source_url,
                        "target_account_type": target_account_type or None,
                        "publish_platforms": publish_platforms or None,
                        "reward_rule_text": reward_rule_text or None,
                        "is_game_related": is_game_related,
                        "task_type": task_type,
                        "unit_price": unit_price or None,
                        "revenue_share": revenue_share or None,
                        "deadline": deadline or None,
                        "account_requirements": account_requirements or None,
                        "material_url": material_url or None,
                        "production_requirements": "\n".join(x for x in [production_requirements, risk_note] if x) or None,
                        "signup_url": signup_url or None,
                    }
                )
                saved = DB.upsert_tasks([task])
                DB.log_import_run(ImportRun("手动链接", "manual_link", saved, 0, "ok", None))
                st.success("\u5df2\u4fdd\u5b58\uff0c\u5df2\u8fdb\u5165\u4efb\u52a1\u5e93\u5e76\u53c2\u4e0e\u8bc4\u5206\u3002")

    st.markdown("#### Excel 导入任务")
    uploaded = st.file_uploader("\u5bfc\u5165 Excel", type=["xlsx"])
    if uploaded:
        tmp = ROOT / "data" / "manual_import.xlsx"
        tmp.write_bytes(uploaded.getvalue())
        preview = preview_excel(tmp)
        st.dataframe(display_tasks(preview), width="stretch", hide_index=True)
        if st.button("确认导入 Excel"):
            imported = import_excel(tmp)
            saved = DB.upsert_tasks(imported)
            DB.log_import_run(ImportRun(uploaded.name, "excel", saved, 0, "ok", None))
            st.success(f"\u5df2\u5bfc\u5165 {saved} \u6761\uff08\u91cd\u590d\u4efb\u52a1\u5df2\u66f4\u65b0\uff0c\u4e0d\u4f1a\u91cd\u590d\u5199\u5165\uff09\u3002")

    df = analyzed_tasks(selected_profile)
    if not df.empty and st.button("\u5bfc\u51fa Excel"):
        out = ROOT / "data" / "exports" / "tasks_with_analysis.xlsx"
        export_excel(df, out)
        st.success(f"\u5df2\u5bfc\u51fa\uff1a{out}")

with tabs[7]:
    st.subheader(LABELS["tabs"][7])
    with st.form("data_source_form"):
        source_name = st.text_input("名称")
        source_platform = st.selectbox("平台", SOURCE_PLATFORMS)
        source_category = st.selectbox("任务分类", list(CATEGORY_OPTIONS.keys()), format_func=lambda x: CATEGORY_OPTIONS.get(x, x))
        collection_method = st.selectbox("采集方式", COLLECTION_METHODS)
        source_link = st.text_input("链接")
        source_enabled = st.checkbox("是否启用", value=True)
        source_frequency = st.selectbox("采集频率", ["manual", "daily", "weekly", "monthly"])
        source_notes = st.text_area("备注")
        if st.form_submit_button("保存数据源"):
            if not source_name.strip():
                st.error("数据源名称不能为空。")
            else:
                DB.upsert_data_source(
                    DataSource(
                        name=source_name.strip(),
                        platform=source_platform,
                        task_category=source_category,
                        collection_method=collection_method,
                        link=source_link or None,
                        enabled=source_enabled,
                        frequency=source_frequency,
                        notes=source_notes or None,
                    )
                )
                st.success("已保存数据源。")

    sources_df = DB.df("data_sources")
    if sources_df.empty:
        cfg = sources_config()
        legacy_sources = pd.DataFrame(cfg["sources"])
        st.info("暂无自定义数据源。下方展示配置文件中的内置来源。")
        st.dataframe(display_tasks(legacy_sources), width="stretch", hide_index=True)
    else:
        platform_view = st.selectbox("按平台查看", ["全部"] + SOURCE_PLATFORMS)
        shown_sources = sources_df if platform_view == "全部" else sources_df[sources_df["platform"] == platform_view]
        st.dataframe(display_tasks(shown_sources), width="stretch", hide_index=True)
        source_keys = shown_sources["source_key"].tolist()
        if source_keys:
            selected_source_key = st.selectbox("启用/停用数据源", source_keys)
            selected_source = shown_sources[shown_sources["source_key"] == selected_source_key].iloc[0].to_dict()
            enabled_value = st.checkbox("启用选中数据源", value=bool(selected_source["enabled"]))
            if st.button("更新启用状态"):
                DB.set_data_source_enabled(selected_source_key, enabled_value)
                st.success("已更新启用状态。")
            if st.button("立即采集"):
                if not bool(selected_source.get("enabled")):
                    DB.log_import_run(ImportRun(selected_source.get("name", selected_source_key), "public_web", 0, 1, "blocked", "数据源未启用"))
                    st.error("数据源未启用。")
                elif not selected_source.get("link"):
                    DB.log_import_run(ImportRun(selected_source.get("name", selected_source_key), "public_web", 0, 1, "failed", "数据源缺少链接"))
                    st.error("数据源缺少链接。")
                else:
                    candidates, error = collect_public_web_candidates(
                        str(selected_source["link"]),
                        str(selected_source.get("platform") or "品牌官网"),
                        str(selected_source.get("task_category") or "other"),
                    )
                    records = []
                    existing_tasks = raw_tasks()
                    for candidate in candidates:
                        rec = candidate.to_record()
                        rec["duplicate_hint"] = duplicate_hint(rec, existing_tasks)
                        records.append(rec)
                    st.session_state["crawl_preview"] = {
                        "source_key": selected_source_key,
                        "source_name": selected_source.get("name"),
                        "frequency": selected_source.get("frequency") or "manual",
                        "records": records,
                        "error": error,
                    }
                    status = "ok" if records else "failed"
                    DB.log_import_run(ImportRun(selected_source.get("name", selected_source_key), "public_web", len(records), 0 if records else 1, status, error))
                    if error:
                        st.error(f"采集失败：{error}")
                    else:
                        st.success(f"采集完成，识别到 {len(records)} 条候选任务。")

    if "crawl_preview" in st.session_state:
        st.markdown("#### 采集预览")
        preview_state = st.session_state["crawl_preview"]
        preview_records = preview_state.get("records", [])
        if preview_records:
            preview_cols = ["task_name", "source_url", "platform", "task_category", "reward_rule_text", "confidence", "duplicate_hint"]
            st.dataframe(display_tasks(pd.DataFrame(preview_records)[preview_cols]), width="stretch", hide_index=True)
            if st.button("确认写入采集结果"):
                tasks = [task_from_row(record) for record in preview_records]
                saved = DB.upsert_tasks(tasks)
                DB.mark_data_source_collected(preview_state["source_key"], preview_state.get("frequency") or "manual")
                DB.log_import_run(ImportRun(preview_state.get("source_name") or preview_state["source_key"], "public_web_confirm", saved, 0, "ok", None))
                st.success(f"已写入/更新 {saved} 条任务。")
        else:
            st.info("暂无可写入的采集候选。")

    cfg = sources_config()
    phase1 = {s["key"]: s for s in cfg["sources"] if s.get("phase") == 1}
    col1, col2 = st.columns(2)
    with col1:
        if st.button("\u91c7\u96c6\u6296\u97f3\u516c\u5f00\u9875\u9762"):
            source = phase1["douyin_game_publisher"]
            result = DouyinGamePublisherAdapter(source["public_urls"], ROOT / "data" / "snapshots").collect()
            DB.upsert_tasks(result.tasks)
            DB.log_run(source["key"], ",".join(source["public_urls"]), result.status, result.message, len(result.tasks), 0 if result.status == "ok" else 1)
            st.success(f"\u91c7\u96c6\u5b8c\u6210\uff1a{len(result.tasks)} \u6761\u3002")
    with col2:
        if st.button("\u91c7\u96c6\u5feb\u624b\u661f\u706b\u516c\u5f00\u9875\u9762"):
            source = phase1["kuaishou_spark"]
            result = KuaishouSparkAdapter(source["public_urls"], ROOT / "data" / "snapshots").collect()
            DB.upsert_tasks(result.tasks)
            DB.log_run(source["key"], ",".join(source["public_urls"]), result.status, result.message, len(result.tasks), 0 if result.status == "ok" else 1)
            st.success(f"\u91c7\u96c6\u5b8c\u6210\uff1a{len(result.tasks)} \u6761\u3002")

with tabs[8]:
    st.subheader(LABELS["tabs"][8])
    df = raw_tasks()
    if df.empty:
        st.info("\u6682\u65e0\u4efb\u52a1\u3002")
    else:
        with st.form("task_note"):
            selected = st.selectbox(LABELS["task"], df["dedupe_key"].tolist())
            note = st.text_area("\u4eba\u5de5\u5907\u6ce8", placeholder="\u4f8b\u5982\uff1a\u5df2\u62a5\u540d\u3001\u5df2\u53d1\u5e03\u3001\u6700\u7ec8\u6548\u679c\u3001\u7ed3\u7b97\u5907\u6ce8\u7b49")
            if st.form_submit_button("\u4fdd\u5b58\u5907\u6ce8"):
                DB.add_task_note(TaskNote(selected, note))
                st.success("\u5df2\u4fdd\u5b58\u5907\u6ce8\u3002")
    st.dataframe(display_tasks(DB.df("task_notes")), width="stretch", hide_index=True)

with tabs[9]:
    st.subheader(LABELS["tabs"][9])
    records = DB.df("import_runs")
    if records.empty:
        st.info("暂无采集或导入记录。")
    else:
        st.dataframe(display_tasks(records), width="stretch", hide_index=True)
    with st.expander("旧采集日志"):
        st.dataframe(display_tasks(DB.df("crawl_runs")), width="stretch", hide_index=True)

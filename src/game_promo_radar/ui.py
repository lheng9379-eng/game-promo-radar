from __future__ import annotations

from io import BytesIO
import json
from typing import Any

import pandas as pd
import streamlit as st

from .rules import display_value, is_missing

CORE_FIELDS = ["reward_description", "account_requirements", "deadline", "material_url", "production_requirements"]

FEASIBILITY_COLORS = {
    "推荐做": "#17803a",
    "可以做": "#1d5fd1",
    "观望": "#a16207",
    "不建议做": "#b42318",
    "信息不足": "#667085",
}

DIFFICULTY_COLORS = {
    "简单": "#17803a",
    "一般": "#1d5fd1",
    "较难": "#c05621",
    "困难": "#b42318",
    "无法判断": "#667085",
}


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1360px; }
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 10px 12px;
        }
        .radar-card {
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 12px 14px;
            margin-bottom: 10px;
            background: #ffffff;
        }
        .radar-title { font-weight: 650; font-size: 1rem; margin: 4px 0 8px 0; }
        .radar-meta { color: #475467; font-size: .86rem; margin-bottom: 8px; }
        .badge {
            display: inline-block;
            border-radius: 999px;
            padding: 2px 8px;
            color: white;
            font-size: .78rem;
            line-height: 1.5;
            margin-right: 5px;
            white-space: nowrap;
        }
        .muted { color: #667085; }
        .evidence { margin: 4px 0 0 0; padding-left: 1.1rem; color: #344054; }
        .detail-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 8px 18px;
        }
        .detail-item { border-bottom: 1px solid #f2f4f7; padding-bottom: 5px; overflow-wrap: anywhere; }
        .detail-label { color: #667085; font-size: .8rem; }
        .detail-value { color: #101828; }
        @media (max-width: 900px) {
            .detail-grid { grid-template-columns: 1fr; }
            .block-container { padding-left: .8rem; padding-right: .8rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def badge(text: Any, palette: dict[str, str]) -> str:
    value = str(display_value(text))
    color = palette.get(value, "#667085")
    return f'<span class="badge" style="background:{color}">{value}</span>'


def reward_text(row: dict[str, Any]) -> Any:
    if not is_missing(row.get("reward_description")):
        return row.get("reward_description")
    if not is_missing(row.get("unit_price")):
        return row.get("unit_price")
    if not is_missing(row.get("revenue_share")):
        return row.get("revenue_share")
    return None


def field_completeness(row: dict[str, Any]) -> float:
    present = sum(0 if is_missing(row.get(field)) else 1 for field in CORE_FIELDS)
    return round(present / len(CORE_FIELDS), 2)


def evidence_items(text: Any, limit: int = 3) -> list[str]:
    if is_missing(text):
        return []
    items = [item.strip(" -") for item in str(text).replace("\r", "\n").split("\n") if item.strip()]
    return items[:limit]


def display_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    shown = df.astype("object").copy()
    for col in shown.columns:
        shown[col] = shown[col].apply(display_value)
    return shown.astype(str)


def task_card(row: dict[str, Any], key: str) -> None:
    evidence = evidence_items(row.get("判断依据"), 3)
    st.markdown(
        f"""
        <div class="radar-card">
          <div class="radar-meta">{display_value(row.get("platform"))} / {display_value(row.get("game_name"))}</div>
          <div class="radar-title">{display_value(row.get("task_name"))}</div>
          <div>
            {badge(row.get("可做性"), FEASIBILITY_COLORS)}
            {badge(row.get("制作难度"), DIFFICULTY_COLORS)}
            <span class="muted">截止：{display_value(row.get("截止状态"))}</span>
          </div>
          <div class="radar-meta">奖励/收益：{display_value(reward_text(row))}</div>
          <div class="radar-meta">缺失字段：{display_value(row.get("未获取字段"))}</div>
          <ul class="evidence">
            {''.join(f'<li>{item}</li>' for item in evidence)}
          </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns([1, 3])
    with col1:
        if not is_missing(row.get("source_url")):
            st.link_button("来源链接", str(row.get("source_url")), width="stretch")
    with col2:
        with st.expander("查看详情", expanded=False):
            task_detail(row, key)


def task_detail(row: dict[str, Any], key: str = "detail") -> None:
    fields = [
        ("基础信息", f"{display_value(row.get('platform'))} / {display_value(row.get('game_name'))} / {display_value(row.get('task_name'))}"),
        ("奖励/收益", reward_text(row)),
        ("报名门槛", row.get("account_requirements")),
        ("截止时间", row.get("deadline")),
        ("生命周期", row.get("生命周期")),
        ("素材要求", row.get("material_url")),
        ("制作要求", row.get("production_requirements")),
        ("是否真人出镜", row.get("requires_real_person")),
        ("是否原创拍摄", row.get("requires_original_shooting")),
        ("是否复杂剪辑", row.get("requires_complex_editing")),
        ("公开热度线索", row.get("public_heat_clues")),
        ("竞争程度线索", row.get("competition_clues")),
        ("可能的详情链接", row.get("candidate_links")),
        ("图片/海报路径", row.get("image_paths")),
        ("OCR 状态", row.get("ocr_status")),
        ("OCR 文本", row.get("ocr_text")),
        ("命中的价值关键词", row.get("value_keywords")),
        ("缺失字段诊断", row.get("未获取字段")),
        ("高价值待确认", "是" if row.get("高价值待确认") is True else None),
        ("可做性判断", row.get("可做性")),
        ("制作难度判断", row.get("制作难度")),
        ("来源链接", row.get("source_url")),
        ("原始快照路径", row.get("raw_snapshot")),
        ("结果备注/结算备注", row.get("result_note")),
    ]
    html = ['<div class="detail-grid">']
    for label, value in fields:
        html.append(
            f'<div class="detail-item"><div class="detail-label">{label}</div>'
            f'<div class="detail-value">{display_value(value)}</div></div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)
    st.markdown("**判断依据**")
    items = evidence_items(row.get("判断依据"), 20)
    if items:
        for item in items:
            st.write(f"- {item}")
    else:
        st.write("待确认")
    st.markdown("**游戏热度**")
    st.write(f"趋势：{display_value(row.get('heat_trend'))}；指数：{display_value(row.get('heat_index'))}；来源：{display_value(row.get('heat_source'))}")
    st.write(display_value(row.get("heat_notes")))
    st.markdown("**榜单表现**")
    st.write(f"来源：{display_value(row.get('app_rank_source'))}；排名：{display_value(row.get('app_rank_position'))}；变化：{display_value(row.get('app_rank_change'))}")
    st.markdown("**买量投放**")
    st.write(f"趋势：{display_value(row.get('ad_trend'))}；素材数：{display_value(row.get('ad_material_count'))}；平台：{display_value(row.get('ad_platforms'))}")
    st.markdown("**同类爆款样本**")
    st.write(f"样本数：{display_value(row.get('sample_count'))}；最高点赞：{display_value(row.get('top_sample_like_count'))}")
    st.write(f"代表样本：{display_value(row.get('top_sample_title'))} {display_value(row.get('top_sample_url'))}")
    st.markdown("**素材完整度**")
    st.write(
        f"评分：{display_value(row.get('material_score'))}；官方素材：{display_value(row.get('has_official_material'))}；"
        f"视频素材：{display_value(row.get('has_video_material'))}；脚本模板：{display_value(row.get('has_script_template'))}"
    )
    st.write(display_value(row.get("material_notes")))
    st.markdown("**风险信号**")
    st.write(f"风险等级：{display_value(row.get('risk_level'))}；关键词：{display_value(row.get('risk_keywords'))}")
    st.write(display_value(row.get("risk_notes")))


def dataframe_downloads(df: pd.DataFrame, report: dict[str, Any]) -> tuple[bytes, bytes]:
    json_bytes = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    excel = BytesIO()
    with pd.ExcelWriter(excel, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="tasks", index=False)
        pd.DataFrame([report]).to_excel(writer, sheet_name="report", index=False)
    return json_bytes, excel.getvalue()


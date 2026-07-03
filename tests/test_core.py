from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from game_promo_radar.analysis import DIFFICULTY_LABELS, FEASIBILITY_LABELS, analyze_task
from game_promo_radar.adapters.manual import export_excel, import_excel, task_from_row
from game_promo_radar.adapters.public_web import parse_public_page
from game_promo_radar.db import RadarDB
from game_promo_radar.intel import (
    DEMO_TASK_KEY,
    extension_excel_template,
    insert_demo_intel,
    load_intel_sources,
    save_pending_intel_link,
)
from game_promo_radar.models import Task, TaskNote
from game_promo_radar.online_collect import (
    SearchResult,
    DEFAULT_DETAIL_SEEDS,
    collect_detail_seed_urls,
    collect_public_urls,
    extract_similar_detail_links,
    extract_bilibili_activity_links,
    extract_candidate_links,
    extract_image_urls,
    is_detail_page,
    is_entry_page,
    is_relevant_result,
    is_high_value_pending,
    ocr_images,
    quality_summary,
    reparse_saved_snapshots,
    save_page_images,
    high_value_pending_task_from_html,
    task_from_public_html,
)
from game_promo_radar.rules import deadline_status, display_value, is_missing
from game_promo_radar.rules import lifecycle_status
from game_promo_radar.scheduler import (
    AutoCollectConfig,
    append_auto_run,
    generate_alerts,
    load_auto_config,
    load_auto_runs,
    next_collect_time,
    save_auto_config,
    should_run_auto_collect,
)


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


def test_upsert_does_not_overwrite_existing_fields_with_null(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    first = Task(
        "抖音",
        "游戏A",
        "任务A",
        "https://example.com/a",
        task_id="A1",
        unit_price=3.5,
        deadline="2999-01-01",
        material_url="https://example.com/material",
        production_requirements="使用官方素材剪辑",
        first_seen_at="2026-01-01T00:00:00",
    )
    second = Task(
        "抖音",
        None,
        "任务A更新",
        "https://example.com/a",
        task_id="A1",
        unit_price=None,
        deadline=None,
        material_url=None,
        production_requirements=None,
    )
    db.upsert_tasks([first])
    db.upsert_tasks([second])
    row = db.df("tasks").iloc[0]
    assert row["first_seen_at"] == "2026-01-01T00:00:00"
    assert row["task_name"] == "任务A更新"
    assert row["game_name"] == "游戏A"
    assert row["unit_price"] == 3.5
    assert row["deadline"] == "2999-01-01"
    assert row["material_url"] == "https://example.com/material"
    assert row["production_requirements"] == "使用官方素材剪辑"
    assert not is_missing(row["last_seen_at"])


def test_deadline_status():
    assert deadline_status("2026-06-29", date(2026, 6, 30)) == "已截止"
    assert deadline_status("2026-07-02", date(2026, 6, 30)) == "即将截止"
    assert deadline_status("2026-07-20", date(2026, 6, 30)) == "进行中"
    assert deadline_status(None, date(2026, 6, 30)) == "待确认"
    assert lifecycle_status("2026-07-05", "2026-07-20", date(2026, 6, 30)) == "即将开始"
    assert lifecycle_status("2026-06-01", "2026-07-02", date(2026, 6, 30)) == "即将截止"
    assert lifecycle_status("2026-06-01", "2026-07-20", date(2026, 6, 30)) == "进行中"
    assert lifecycle_status("2026-06-01", "2026-06-20", date(2026, 6, 30)) == "已截止"


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
    assert result.feasibility in FEASIBILITY_LABELS
    assert result.difficulty in DIFFICULTY_LABELS


def test_analysis_downgrades_expired_tasks():
    task = Task(
        "TapTap",
        "游戏",
        "过期活动",
        "https://example.com/expired",
        reward_description="现金奖励500元",
        deadline="2026-06-01",
        account_requirements="无门槛",
        material_url="官方素材",
        production_requirements="原创攻略视频",
    ).to_record()
    result = analyze_task(task)
    assert result.feasibility == "不建议做"
    assert any("已截止" in item for item in result.evidence)


def test_analysis_marks_missing_information():
    task = Task("快手", "待确认", "公开通告", "https://example.com/b").to_record()
    result = analyze_task(task)
    assert result.feasibility == "信息不足"
    assert result.difficulty == "无法判断"
    assert "收益或奖励未获取到，不能推测。" in result.evidence
    assert "公开作品热度" in result.missing_fields
    assert result.feasibility in FEASIBILITY_LABELS
    assert result.difficulty in DIFFICULTY_LABELS
    assert len(result.evidence) > 0


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


def test_public_page_parser_extracts_explicit_intelligence_fields():
    html = """
    <html><head><title>暑期推广任务公告</title></head>
    <body>
      <h1>公开招募</h1>
      <p>任务名称：暑期新游推广</p>
      <p>平台：抖音</p>
      <p>游戏名称：测试游戏</p>
      <p>奖励/收益：CPA 3.5元/激活，分成30%</p>
      <p>报名门槛：粉丝1000以上</p>
      <p>截止时间：2026年07月31日</p>
      <p>素材要求：使用官方素材包</p>
      <p>制作要求：需要真人出镜、原创拍摄、复杂剪辑</p>
      <p>热度：已有2000人参与投稿</p>
      <p>竞争：排行榜前50名发放奖励</p>
    </body></html>
    """
    intel = parse_public_page(html, "抖音")
    assert intel.page_title == "暑期推广任务公告"
    assert intel.task_name == "暑期新游推广"
    assert intel.platform == "抖音"
    assert intel.game_name == "测试游戏"
    assert intel.reward_description == "CPA 3.5元/激活，分成30%"
    assert intel.unit_price == 3.5
    assert intel.revenue_share == 30
    assert intel.account_requirements == "粉丝1000以上"
    assert intel.deadline == "2026-07-31"
    assert intel.material_requirements == "使用官方素材包"
    assert intel.production_requirements == "需要真人出镜、原创拍摄、复杂剪辑"
    assert intel.requires_real_person is True
    assert intel.requires_original_shooting is True
    assert intel.requires_complex_editing is True
    assert intel.public_heat_clues == "已有2000人参与投稿"
    assert intel.competition_clues == "排行榜前50名发放奖励"


def test_public_page_parser_does_not_guess_missing_fields():
    html = """
    <html><head><title>平台公告</title></head>
    <body><p>这里是普通说明，没有任务奖励、门槛、素材或截止日期。</p></body></html>
    """
    intel = parse_public_page(html, "快手")
    assert intel.page_title == "平台公告"
    assert intel.platform == "快手"
    assert intel.task_name is None
    assert intel.game_name is None
    assert intel.reward_description is None
    assert intel.unit_price is None
    assert intel.revenue_share is None
    assert intel.account_requirements is None
    assert intel.deadline is None
    assert intel.material_requirements is None
    assert intel.production_requirements is None
    assert intel.requires_real_person is None
    assert intel.requires_original_shooting is None
    assert intel.requires_complex_editing is None


def test_public_parse_null_fields_do_not_overwrite_existing_task_data(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    old = Task(
        "抖音",
        "旧游戏",
        "旧任务",
        "https://example.com/public",
        task_id="PUBLIC-1",
        reward_description="奖励明确",
        account_requirements="粉丝1000以上",
        deadline="2999-01-01",
        material_url="官方素材包",
        production_requirements="剪辑发布",
    )
    intel = parse_public_page("<html><head><title>旧任务</title></head><body>普通公告</body></html>", "抖音")
    new = Task(
        intel.platform or "抖音",
        intel.game_name,
        intel.task_name or intel.page_title or "旧任务",
        "https://example.com/public",
        task_id="PUBLIC-1",
        page_title=intel.page_title,
        reward_description=intel.reward_description,
        account_requirements=intel.account_requirements,
        deadline=intel.deadline,
        material_url=intel.material_requirements,
        production_requirements=intel.production_requirements,
    )
    db.upsert_tasks([old])
    db.upsert_tasks([new])
    row = db.df("tasks").iloc[0]
    assert row["game_name"] == "旧游戏"
    assert row["reward_description"] == "奖励明确"
    assert row["account_requirements"] == "粉丝1000以上"
    assert row["deadline"] == "2999-01-01"
    assert row["material_url"] == "官方素材包"
    assert row["production_requirements"] == "剪辑发布"


def test_search_result_filter_keeps_only_public_game_promo_candidates():
    assert is_relevant_result(SearchResult("某游戏创作者激励活动", "https://example.com/a", "投稿奖励"))
    assert is_relevant_result(SearchResult("抖音游戏发行人任务", "https://example.com/b", "推广任务"))
    assert not is_relevant_result(SearchResult("普通新闻", "https://example.com/c", "没有活动信息"))
    assert not is_relevant_result(SearchResult("游戏推广招聘", "https://example.com/d", "招聘代运营"))


def test_task_from_public_html_saves_snapshot_and_generates_task(tmp_path):
    html = """
    <html><head><title>任务公告</title></head><body>
    <p>任务名称：快手游戏推广任务</p>
    <p>游戏名称：测试游戏</p>
    <p>奖励：5元/激活</p>
    <p>报名门槛：无门槛</p>
    <p>截止时间：2999-01-01</p>
    <p>制作要求：使用官方素材剪辑</p>
    </body></html>
    """
    task = task_from_public_html("https://www.kuaishou.com/task", html, tmp_path)
    assert task.platform == "快手"
    assert task.task_name == "快手游戏推广任务"
    assert task.unit_price == 5
    assert task.raw_snapshot is not None
    assert (tmp_path / Path(task.raw_snapshot).name).exists()


def test_online_collect_dedupes_repeated_public_tasks_and_generates_analysis(tmp_path, monkeypatch):
    db = RadarDB(tmp_path / "radar.duckdb")
    html = """
    <html><head><title>任务公告</title></head><body>
    <p>任务名称：公开游戏任务</p>
    <p>游戏名称：测试游戏</p>
    <p>奖励：5元/激活</p>
    <p>报名门槛：无门槛</p>
    <p>截止时间：2999-01-01</p>
    <p>素材要求：官方素材</p>
    <p>制作要求：简单剪辑即可</p>
    </body></html>
    """

    def fake_fetch(url: str) -> str:
        return html

    import game_promo_radar.online_collect as online_collect

    monkeypatch.setattr(online_collect, "fetch_public_html", fake_fetch)
    sources = [
        ("source_a", "抖音", "https://example.com/task"),
        ("source_a", "抖音", "https://example.com/task"),
    ]
    result = collect_public_urls(db, sources, tmp_path, pause_seconds=0)
    assert result.success_count == 2
    assert result.new_count == 1
    assert result.updated_count == 1
    assert len(db.df("tasks")) == 1
    analysis = analyze_task(db.df("tasks").iloc[0].to_dict())
    assert analysis.feasibility in FEASIBILITY_LABELS
    assert analysis.difficulty in DIFFICULTY_LABELS
    assert analysis.evidence


def test_entry_page_is_not_written_without_detail_fields(tmp_path, monkeypatch):
    db = RadarDB(tmp_path / "radar.duckdb")
    html = """
    <html><head><title>平台首页</title></head><body>
      <a href="/about">产品介绍</a>
      <a href="/login">登录</a>
    </body></html>
    """

    import game_promo_radar.online_collect as online_collect

    monkeypatch.setattr(online_collect, "fetch_public_html", lambda url: html)
    result = collect_public_urls(db, [("home", "抖音", "https://example.com/")], tmp_path, pause_seconds=0)
    assert result.entry_page_count == 1
    assert result.written_count == 0
    assert len(db.df("tasks")) == 0


def test_detail_page_must_meet_field_threshold(tmp_path, monkeypatch):
    db = RadarDB(tmp_path / "radar.duckdb")
    weak_html = "<html><head><title>普通公告</title></head><body>只有一个游戏标题</body></html>"
    strong_html = """
    <html><head><title>活动规则</title></head><body>
      <p>任务名称：攻略征集活动</p>
      <p>游戏名称：测试游戏</p>
      <p>奖励：1000元奖金</p>
      <p>参与方式：投稿攻略视频</p>
      <p>截止时间：2999-01-01</p>
      <p>制作要求：攻略图文或视频均可</p>
    </body></html>
    """

    import game_promo_radar.online_collect as online_collect

    pages = {"https://example.com/weak": weak_html, "https://example.com/activity/strong": strong_html}
    monkeypatch.setattr(online_collect, "fetch_public_html", lambda url: pages[url])
    result = collect_public_urls(
        db,
        [("weak", "其他", "https://example.com/weak"), ("strong", "其他", "https://example.com/activity/strong")],
        tmp_path,
        pause_seconds=0,
    )
    assert result.written_count == 1
    assert result.filtered_count == 1
    assert db.df("tasks").iloc[0]["task_name"] == "攻略征集活动"


def test_bilibili_blackboard_activity_page_is_recognized():
    url = "https://www.bilibili.com/blackboard/activity-game-award.html"
    html = """
    <html><head><title>B站游戏激励活动</title></head><body>
      <p>活动名称：游戏投稿奖励活动</p>
      <p>游戏名称：测试游戏</p>
      <p>奖励：最高5000元奖金</p>
      <p>投稿方式：发布游戏视频并带话题</p>
      <p>活动时间：2999-01-01 截止</p>
      <p>活动规则：按播放和互动评奖</p>
    </body></html>
    """
    intel = parse_public_page(html, "B站")
    assert is_detail_page(intel, url, html)
    assert not is_entry_page(url, html)


def test_taptap_moment_or_activity_page_is_recognized():
    for url in ["https://www.taptap.cn/moment/123", "https://www.taptap.cn/activity/abc"]:
        html = """
        <html><head><title>TapTap 创作者激励</title></head><body>
          <p>活动名称：二创活动</p>
          <p>游戏名称：测试游戏</p>
          <p>奖励：周边和现金奖励</p>
          <p>参与方式：发布图文攻略</p>
          <p>截止时间：2999-01-01</p>
        </body></html>
        """
        intel = parse_public_page(html, "TapTap")
        assert is_detail_page(intel, url, html)


def test_platform_activity_parser_extracts_unstructured_fields():
    html = """
    <html><head><title>《测试游戏》B站投稿激励活动</title></head><body>
      <h1>《测试游戏》二创投稿激励</h1>
      <p>本次活动设置现金奖励，最高1000元奖金。</p>
      <p>参与方式：发布游戏视频并带指定话题投稿。</p>
      <p>活动时间：2999-01-01 至 2999-02-01。</p>
      <p>作品要求：攻略、二创视频或直播切片均可，需原创内容。</p>
    </body></html>
    """
    intel = parse_public_page(html, "B站")
    assert intel.task_name == "《测试游戏》B站投稿激励活动"
    assert intel.game_name == "测试游戏"
    assert intel.reward_description == "本次活动设置现金奖励，最高1000元奖金"
    assert intel.account_requirements == "发布游戏视频并带指定话题投稿"
    assert intel.deadline == "2999-02-01"
    assert intel.start_time == "2999-01-01"
    assert intel.production_requirements == "攻略、二创视频或直播切片均可，需原创内容"
    assert intel.requires_original_shooting is True


def test_high_value_pending_detects_reward_and_submission_terms():
    task = {
        "task_name": "二创投稿活动",
        "reward_description": None,
        "account_requirements": None,
        "deadline": None,
        "production_requirements": None,
        "public_heat_clues": None,
    }
    assert is_high_value_pending(task, "现金奖励 投稿 活动时间待确认")


def test_log_message_replaces_question_mark_garbled_text(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    db.log_run("source", "https://example.com", "blocked", "????????", 0, 1, 0, 0)
    logs = db.df("crawl_runs")
    assert "????" not in logs.iloc[0]["message"]
    assert "编码异常内容" in logs.iloc[0]["message"]


def test_bilibili_video_description_extracts_blackboard_link():
    html = """
    <html><body>
      <p>活动详情：https://www.bilibili.com/blackboard/activity-game-award.html</p>
      <a href="https://www.bilibili.com/video/BV123">普通视频</a>
    </body></html>
    """
    links = extract_bilibili_activity_links(html)
    assert links == ["https://www.bilibili.com/blackboard/activity-game-award.html"]


def test_default_detail_seed_pool_includes_expanded_taptap_urls():
    urls = [url for _, _, url in DEFAULT_DETAIL_SEEDS]
    assert "https://www.taptap.cn/moment/809013787729330483" in urls
    assert "https://www.taptap.cn/moment/786187752067564616" in urls
    assert "https://www.taptap.cn/moment/798507701024851113" in urls
    assert len(urls) >= 10


def test_extract_similar_detail_links_keeps_taptap_incentive_links():
    html = """
    <html><body>
      <a href="https://www.taptap.cn/moment/1">普通攻略</a>
      <a href="https://www.taptap.cn/moment/2">TapTap 创作激励 活动</a>
      <a href="https://www.taptap.cn/moment/3">攻略征集 投稿奖励</a>
    </body></html>
    """
    links = extract_similar_detail_links("https://www.taptap.cn/moment/source", html)
    urls = [item.url for item in links]
    assert "https://www.taptap.cn/moment/2" in urls
    assert "https://www.taptap.cn/moment/3" in urls
    assert "https://www.taptap.cn/moment/1" not in urls


def test_bilibili_opus_high_value_pending_saves_images_without_detail_threshold(tmp_path, monkeypatch):
    html = """
    <html><head><title>B站投稿活动长图说明</title></head><body>
      <p>活动群与报名问卷见长图，投稿奖励待确认。</p>
      <img src="https://cdn.example.com/poster.jpg">
    </body></html>
    """

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"fake-image"

    import game_promo_radar.online_collect as online_collect

    monkeypatch.setattr(online_collect, "urlopen", lambda req, timeout=20: FakeResponse())
    monkeypatch.setattr(online_collect, "which", lambda name: None)
    task = high_value_pending_task_from_html("https://www.bilibili.com/opus/1", html, tmp_path, "B站")
    assert task.platform == "B站"
    assert task.ocr_status == "图片待识别"
    assert task.image_paths is not None
    assert "奖励" in (task.value_keywords or "")


def test_image_urls_are_saved_and_ocr_unavailable_does_not_fail(tmp_path, monkeypatch):
    html = '<html><body><img src="https://cdn.example.com/poster.jpg"></body></html>'
    urls = extract_image_urls("https://example.com/activity", html)
    assert urls == ["https://cdn.example.com/poster.jpg"]

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"fake-image"

    import game_promo_radar.online_collect as online_collect

    monkeypatch.setattr(online_collect, "urlopen", lambda req, timeout=20: FakeResponse())
    saved = save_page_images(urls, tmp_path, "https://example.com/activity")
    assert any(Path(item).name.endswith(".jpg") for item in saved)
    assert any(Path(item).name.startswith("manifest-") for item in saved)
    monkeypatch.setattr(online_collect, "which", lambda name: None)
    text, status = ocr_images(saved)
    assert text is None
    assert status == "图片待识别"


def test_ocr_unavailable_does_not_overwrite_existing_fields_with_null(tmp_path, monkeypatch):
    db = RadarDB(tmp_path / "radar.duckdb")
    snapshot_dir = tmp_path / "data" / "snapshots"
    snapshot_dir.mkdir(parents=True)
    snapshot = snapshot_dir / "detail.html"
    snapshot.write_text(
        '<html><head><title>活动页</title></head><body><img src="https://cdn.example.com/poster.jpg"></body></html>',
        encoding="utf-8",
    )
    old = Task(
        "B站",
        "旧游戏",
        "旧任务",
        "https://www.bilibili.com/blackboard/activity-old.html",
        reward_description="已有奖励",
        account_requirements="已有门槛",
        deadline="2999-01-01",
        production_requirements="已有制作要求",
        raw_snapshot=str(snapshot.relative_to(tmp_path)),
    )
    db.upsert_tasks([old])

    import game_promo_radar.online_collect as online_collect

    monkeypatch.setattr(online_collect, "which", lambda name: None)
    result = reparse_saved_snapshots(db, tmp_path)
    row = db.df("tasks").iloc[0]
    assert result.failure_count == 0
    assert row["reward_description"] == "已有奖励"
    assert row["account_requirements"] == "已有门槛"


def test_extract_candidate_links_scores_detail_links():
    html = """
    <html><body>
      <a href="/login">登录</a>
      <a href="https://www.bilibili.com/blackboard/activity-game-award.html">游戏投稿奖励活动</a>
      <a href="https://www.taptap.cn/moment/123">创作者激励 投稿奖励</a>
    </body></html>
    """
    links = extract_candidate_links("https://example.com/", html)
    urls = [item.url for item in links]
    assert "https://www.bilibili.com/blackboard/activity-game-award.html" in urls
    assert "https://www.taptap.cn/moment/123" in urls
    assert all("login" not in item.url for item in links)


def test_same_url_has_stable_dedupe_key_even_when_fields_change():
    first = Task("抖音", "待确认", "标题A", "https://example.com/task?utm_source=x")
    second = Task("抖音", None, "标题B", "https://example.com/task")
    assert first.dedupe_key() == second.dedupe_key()


def test_reparse_saved_snapshots_updates_existing_row_without_new_task(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    snapshot_dir = tmp_path / "data" / "snapshots"
    snapshot_dir.mkdir(parents=True)
    snapshot = snapshot_dir / "detail.html"
    snapshot.write_text(
        """
        <html><head><title>《测试游戏》创作者激励活动</title></head><body>
          <p>活动奖励：现金奖励500元。</p>
          <p>参与方式：投稿攻略视频。</p>
          <p>活动时间：2999-01-01 至 2999-02-01。</p>
          <p>素材要求：使用官方素材包。</p>
          <p>制作要求：原创攻略视频。</p>
        </body></html>
        """,
        encoding="utf-8",
    )
    db.upsert_tasks(
        [
            Task(
                "TapTap",
                None,
                "旧活动",
                "https://www.taptap.cn/activity/1",
                raw_snapshot=str(snapshot.relative_to(tmp_path)),
            )
        ]
    )
    result = reparse_saved_snapshots(db, tmp_path)
    rows = db.df("tasks")
    assert result.updated_count == 1
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["game_name"] == "测试游戏"
    assert row["reward_description"] == "现金奖励500元"
    assert row["account_requirements"] == "投稿攻略视频"
    assert row["deadline"] == "2999-02-01"
    assert row["material_url"] == "使用官方素材包"
    assert row["production_requirements"] == "原创攻略视频"


def test_collect_detail_seed_urls_writes_real_detail_task(tmp_path, monkeypatch):
    db = RadarDB(tmp_path / "radar.duckdb")
    html = """
    <html><head><title>《种子游戏》投稿奖励活动</title></head><body>
      <p>任务名称：种子详情页任务</p>
      <p>游戏名称：种子游戏</p>
      <p>活动奖励：现金奖励800元</p>
      <p>参与方式：发布原创攻略视频并带话题投稿</p>
      <p>活动时间：2999-01-01 至 2999-02-01</p>
      <p>素材要求：使用官方素材包</p>
      <p>制作要求：原创攻略视频，无需真人出镜</p>
    </body></html>
    """

    import game_promo_radar.online_collect as online_collect

    monkeypatch.setattr(online_collect, "fetch_public_html", lambda url: html)
    result = collect_detail_seed_urls(
        db,
        [("seed", "TapTap", "https://www.taptap.cn/moment/1")],
        tmp_path,
        pause_seconds=0,
    )
    rows = db.df("tasks")
    assert result.written_count == 1
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["platform"] == "TapTap"
    assert row["game_name"] == "种子游戏"
    assert row["reward_description"] == "现金奖励800元"
    assert row["account_requirements"] == "发布原创攻略视频并带话题投稿"
    assert row["deadline"] == "2999-02-01"
    assert row["production_requirements"] == "原创攻略视频，无需真人出镜"


def test_active_only_seed_collect_keeps_expired_as_history(tmp_path, monkeypatch):
    db = RadarDB(tmp_path / "radar.duckdb")
    html = """
    <html><head><title>已开奖 | 过期投稿奖励活动</title></head><body>
      <p>任务名称：过期详情页任务</p>
      <p>游戏名称：种子游戏</p>
      <p>活动奖励：现金奖励800元</p>
      <p>参与方式：发布原创攻略视频并带话题投稿</p>
      <p>活动时间：2026-01-01 至 2026-02-01</p>
      <p>素材要求：使用官方素材包</p>
      <p>制作要求：原创攻略视频</p>
    </body></html>
    """

    import game_promo_radar.online_collect as online_collect

    monkeypatch.setattr(online_collect, "fetch_public_html", lambda url: html)
    result = collect_detail_seed_urls(
        db,
        [("seed", "TapTap", "https://www.taptap.cn/moment/expired")],
        tmp_path,
        pause_seconds=0,
        active_only=True,
    )
    row = db.df("tasks").iloc[0]
    assert result.written_count == 1
    assert result.filtered_count == 1
    assert row["deadline"] == "2026-02-01"
    assert analyze_task(row.to_dict()).feasibility == "不建议做"


def test_auto_collect_config_save_and_load(tmp_path):
    path = tmp_path / "auto.json"
    config = AutoCollectConfig(enabled=True, daily_time="10:30", use_keyword_search=True)
    save_auto_config(config, path)
    loaded = load_auto_config(path)
    assert loaded.enabled is True
    assert loaded.daily_time == "10:30"
    assert loaded.use_keyword_search is True


def test_auto_collect_enable_disable_and_next_time():
    from datetime import datetime

    disabled = AutoCollectConfig(enabled=False)
    assert next_collect_time(disabled, datetime(2026, 6, 30, 8, 0)) is None
    assert should_run_auto_collect(disabled, None, datetime(2026, 6, 30, 10, 0)) is False
    enabled = AutoCollectConfig(enabled=True, daily_time="09:00")
    assert should_run_auto_collect(enabled, None, datetime(2026, 6, 30, 9, 1)) is True
    assert should_run_auto_collect(enabled, "2026-06-30T09:05:00", datetime(2026, 6, 30, 10, 0)) is False
    assert next_collect_time(enabled, datetime(2026, 6, 30, 10, 0)).date().isoformat() == "2026-07-01"


def test_alert_rules_and_dedupe_for_recommended_and_deadline():
    today = date.today()
    active_start = (today - timedelta(days=30)).isoformat()
    near_deadline = (today + timedelta(days=2)).isoformat()
    df = pd.DataFrame(
        [
            Task(
                "TapTap",
                "游戏",
                "有效推荐任务",
                "https://example.com/alert-a",
                reward_description="现金奖励500元",
                start_time=active_start,
                deadline="2999-02-01",
                account_requirements="无门槛",
                material_url="官方素材",
                production_requirements="原创攻略视频",
            ).to_record(),
            Task(
                "TapTap",
                "游戏",
                "即将截止任务",
                "https://example.com/alert-b",
                reward_description="现金奖励500元",
                start_time=active_start,
                deadline=near_deadline,
                account_requirements="无门槛",
                material_url="官方素材",
                production_requirements="原创攻略视频",
            ).to_record(),
        ]
    )
    alerts = generate_alerts(df)
    assert any(item["type"] == "新增推荐做" for item in alerts)
    assert any(item["type"] == "即将截止" for item in alerts)
    repeated = generate_alerts(df, {item["key"] for item in alerts})
    assert repeated == []


def test_alert_rules_for_failures_and_completeness_drop():
    alerts = generate_alerts(
        pd.DataFrame(),
        collect_summary={
            "created_at": "2026-06-30T09:00:00",
            "failure_count": 2,
            "field_completeness_before": 0.8,
            "field_completeness_after": 0.6,
        },
    )
    assert any(item["type"] == "采集异常" for item in alerts)
    assert any(item["type"] == "字段完整率下降" for item in alerts)


def test_auto_run_log_append_and_load(tmp_path):
    path = tmp_path / "runs.json"
    append_auto_run(path, {"created_at": "2026-06-30T09:00:00", "new_count": 1})
    runs = load_auto_runs(path)
    assert runs[0]["new_count"] == 1


def test_quality_summary_counts_completion_by_platform(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    db.upsert_tasks(
        [
            Task(
                "抖音",
                "游戏A",
                "完整任务",
                "https://example.com/a",
                reward_description="100元",
                account_requirements="无门槛",
                deadline="2999-01-01",
                material_url="素材",
                production_requirements="视频",
            ),
            Task("快手", None, "缺失任务", "https://example.com/b"),
        ]
    )
    quality = quality_summary(db)
    assert quality["field_completeness"] == 0.5
    assert quality["platform_completeness"]["抖音"] == 1.0
    assert quality["platform_completeness"]["快手"] == 0.0


def test_excel_import_export_round_trip(tmp_path):
    source = tmp_path / "tasks.xlsx"
    exported = tmp_path / "exported.xlsx"
    df = pd.DataFrame(
        [
            {
                "platform": "抖音",
                "game_name": "游戏E",
                "task_name": "Excel任务",
                "source_url": "https://example.com/e",
                "unit_price": 1.2,
            }
        ]
    )
    export_excel(df, source)
    tasks = import_excel(source)
    assert len(tasks) == 1
    assert tasks[0].task_name == "Excel任务"
    export_excel(pd.DataFrame([tasks[0].to_record()]), exported)
    assert exported.exists()
    assert pd.read_excel(exported).iloc[0]["task_name"] == "Excel任务"


def test_repeated_collect_keeps_first_seen(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    first = Task("抖音", "游戏A", "任务A", "https://example.com/a", task_id="A1", first_seen_at="2026-01-01T00:00:00")
    second = Task("抖音", "游戏A", "任务A更新", "https://example.com/a", task_id="A1", first_seen_at="2026-02-01T00:00:00")
    db.upsert_tasks([first])
    db.upsert_tasks([second])
    row = db.df("tasks").iloc[0]
    assert row["first_seen_at"] == "2026-01-01T00:00:00"
    assert row["task_name"] == "任务A更新"
    assert not is_missing(row["last_seen_at"])


def test_task_result_note(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    db.add_task_note(TaskNote("k", "已发布，等待平台反馈"))
    notes = db.df("task_notes")
    assert notes.iloc[0]["note"] == "已发布，等待平台反馈"


def test_schema_migration_keeps_existing_tables_and_data(tmp_path):
    path = tmp_path / "radar.duckdb"
    db = RadarDB(path)
    db.upsert_tasks([Task("抖音", "游戏F", "任务F", "https://example.com/f", task_id="F1")])
    db.add_task_note(TaskNote("k", "旧备注"))
    db.log_run("source", "https://example.com", "ok", "旧日志")
    db.con.execute(
        "insert into settlements values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ["k", "https://video", "2026-01-01", 1, 2, 3, 4, 5, 6.0, 7.0, 8.0, "2026-01-02", 1.0],
    )
    db.con.close()

    migrated = RadarDB(path)
    assert len(migrated.df("tasks")) == 1
    assert len(migrated.df("task_notes")) == 1
    assert len(migrated.df("crawl_runs")) == 1
    assert len(migrated.df("settlements")) == 1
    assert "last_seen_at" in migrated.df("tasks").columns


def test_extended_intel_tables_are_created(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    for table in [
        "opportunity_heat_metrics",
        "opportunity_app_ranks",
        "opportunity_ad_intel",
        "opportunity_sample_videos",
        "opportunity_material_assets",
        "opportunity_risk_signals",
    ]:
        assert db.df(table).empty


def test_opportunity_can_have_multiple_sample_videos_and_dedupe(tmp_path):
    db = RadarDB(tmp_path / "radar.duckdb")
    key = "task-1"
    db.upsert_sample_video({"task_dedupe_key": key, "sample_source_url": "https://video/a", "sample_video_title": "A"})
    db.upsert_sample_video({"task_dedupe_key": key, "sample_source_url": "https://video/a", "sample_video_title": "A duplicate"})
    db.upsert_sample_video({"task_dedupe_key": key, "sample_source_url": "https://video/b", "sample_video_title": "B"})
    rows = db.df("opportunity_sample_videos")
    assert len(rows) == 2


def test_heat_trend_increases_recommendation_score():
    base = Task(
        "TapTap",
        "热度游戏",
        "热度任务",
        "https://example.com/heat",
        reward_description="现金奖励500元",
        start_time="2026-06-01",
        deadline="2999-02-01",
        account_requirements="无门槛",
        material_url="官方素材",
        production_requirements="简单攻略视频",
    ).to_record()
    plain = analyze_task(base)
    hot = analyze_task({**base, "heat_trend": "上升", "heat_index": 90})
    assert hot.score > plain.score


def test_material_completeness_reduces_difficulty():
    base = Task(
        "TapTap",
        "素材游戏",
        "素材任务",
        "https://example.com/material-score",
        reward_description="现金奖励500元",
        deadline="2999-02-01",
        account_requirements="无门槛",
        production_requirements="需要剪辑包装",
    ).to_record()
    hard = analyze_task(base)
    easier = analyze_task({**base, "material_score": 10})
    assert easier.difficulty_score < hard.difficulty_score


def test_high_risk_signal_lowers_feasibility():
    task = Task(
        "TapTap",
        "风险游戏",
        "风险任务",
        "https://example.com/risk",
        reward_description="现金奖励500元",
        deadline="2999-02-01",
        account_requirements="无门槛",
        material_url="官方素材",
        production_requirements="简单攻略视频",
    ).to_record()
    safe = analyze_task(task)
    risky = analyze_task({**task, "risk_level": "高"})
    assert risky.score < safe.score
    assert risky.feasibility in {"观望", "不建议做", "信息不足"}


def test_excel_export_contains_extended_columns(tmp_path):
    output = tmp_path / "extended.xlsx"
    df = pd.DataFrame(
        [
            {
                "task_name": "任务",
                "热度趋势": "上升",
                "热度指数": 88,
                "榜单来源": "TapTap",
                "榜单排名": 10,
                "买量趋势": "增强",
                "投放素材数量": 30,
                "爆款样本数量": 2,
                "最高点赞样本": 1000,
                "是否有官方素材": True,
                "是否有视频素材": True,
                "是否有脚本模板": True,
                "素材完整度评分": 8,
                "风险等级": "低",
                "风险备注": "无明显风险",
            }
        ]
    )
    export_excel(df, output)
    exported = pd.read_excel(output)
    assert "热度趋势" in exported.columns
    assert "素材完整度评分" in exported.columns
    assert "风险备注" in exported.columns

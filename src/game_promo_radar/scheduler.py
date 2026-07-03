from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, time, timedelta
import json
from pathlib import Path
from typing import Any

from .analysis import analyze_task
from .online_collect import (
    DEFAULT_CURRENT_DETAIL_SEEDS,
    DEFAULT_DETAIL_SEEDS,
    DEFAULT_SEARCH_QUERIES,
    collect_detail_seed_urls,
    collect_from_search,
    discover_similar_detail_pages,
)
from .rules import is_missing, lifecycle_status


@dataclass
class AutoCollectConfig:
    enabled: bool = False
    daily_time: str = "09:00"
    use_current_seeds: bool = True
    use_all_history_seeds: bool = False
    use_similar_discovery: bool = True
    use_keyword_search: bool = False
    active_only: bool = True


DEFAULT_CONFIG = AutoCollectConfig()


def load_auto_config(path: str | Path) -> AutoCollectConfig:
    file = Path(path)
    if not file.exists():
        save_auto_config(DEFAULT_CONFIG, file)
        return DEFAULT_CONFIG
    data = json.loads(file.read_text(encoding="utf-8"))
    return AutoCollectConfig(**{**asdict(DEFAULT_CONFIG), **data})


def save_auto_config(config: AutoCollectConfig, path: str | Path) -> None:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")


def load_auto_runs(path: str | Path) -> list[dict[str, Any]]:
    file = Path(path)
    if not file.exists():
        return []
    return json.loads(file.read_text(encoding="utf-8"))


def append_auto_run(path: str | Path, record: dict[str, Any]) -> None:
    runs = load_auto_runs(path)
    runs.append(record)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(runs[-100:], ensure_ascii=False, indent=2), encoding="utf-8")


def parse_daily_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))


def next_collect_time(config: AutoCollectConfig, now: datetime | None = None) -> datetime | None:
    if not config.enabled:
        return None
    now = now or datetime.now()
    target = datetime.combine(now.date(), parse_daily_time(config.daily_time))
    if target <= now:
        target += timedelta(days=1)
    return target


def should_run_auto_collect(config: AutoCollectConfig, last_run_at: str | None, now: datetime | None = None) -> bool:
    if not config.enabled:
        return False
    now = now or datetime.now()
    scheduled_today = datetime.combine(now.date(), parse_daily_time(config.daily_time))
    if now < scheduled_today:
        return False
    if is_missing(last_run_at):
        return True
    last = datetime.fromisoformat(str(last_run_at))
    return last.date() < now.date()


def _task_key(task: dict[str, Any]) -> str:
    return str(task.get("dedupe_key") or task.get("source_url") or task.get("task_name"))


def generate_alerts(tasks, previous_alert_keys: set[str] | None = None, collect_summary: dict[str, Any] | None = None) -> list[dict[str, str]]:
    previous_alert_keys = previous_alert_keys or set()
    alerts: list[dict[str, str]] = []
    for task in tasks.to_dict("records"):
        analysis = analyze_task(task)
        lifecycle = lifecycle_status(task.get("start_time"), task.get("deadline"))
        base_key = _task_key(task)
        candidates: list[tuple[str, str]] = []
        if analysis.feasibility == "推荐做" and lifecycle in {"进行中", "即将开始", "即将截止"}:
            candidates.append(("新增推荐做", "推荐做且仍有效"))
        if analysis.feasibility == "可以做" and lifecycle in {"进行中", "即将开始", "即将截止"}:
            candidates.append(("新增可以做", "可以做且仍有效"))
        if lifecycle == "即将截止" and analysis.feasibility != "不建议做":
            candidates.append(("即将截止", "任务即将截止但仍可投稿"))
        if analysis.feasibility == "信息不足" and (
            not is_missing(task.get("value_keywords"))
            or not is_missing(task.get("candidate_links"))
            or not is_missing(task.get("image_paths"))
        ):
            candidates.append(("高价值待确认", "存在奖励、投稿、图片或候选详情线索"))
        for alert_type, reason in candidates:
            key = f"{alert_type}|{base_key}"
            if key in previous_alert_keys:
                continue
            alerts.append({"key": key, "type": alert_type, "task": str(task.get("task_name")), "reason": reason})
    if collect_summary:
        if collect_summary.get("failure_count", 0):
            key = f"采集异常|{collect_summary.get('created_at', '')}"
            alerts.append({"key": key, "type": "采集异常", "task": "自动采集", "reason": f"失败 {collect_summary.get('failure_count')} 条"})
        before = collect_summary.get("field_completeness_before")
        after = collect_summary.get("field_completeness_after")
        if before is not None and after is not None and before - after >= 0.1:
            alerts.append({"key": f"字段完整率下降|{collect_summary.get('created_at', '')}", "type": "字段完整率下降", "task": "自动采集", "reason": f"{before} -> {after}"})
    return alerts


def run_auto_collect(db, config: AutoCollectConfig, snapshot_dir: str | Path, project_root: str | Path) -> dict[str, Any]:
    from .ui import field_completeness

    before_df = db.df("tasks")
    before_completeness = 0.0 if before_df.empty else round(sum(field_completeness(row) for row in before_df.to_dict("records")) / len(before_df), 2)
    total_new = total_updated = total_success = total_failure = 0
    failures: list[str] = []
    if config.use_current_seeds:
        result = collect_detail_seed_urls(db, DEFAULT_CURRENT_DETAIL_SEEDS, snapshot_dir, active_only=config.active_only)
        total_new += result.new_count
        total_updated += result.updated_count
        total_success += result.success_count
        total_failure += result.failure_count
        failures.extend(result.failures)
    if config.use_all_history_seeds:
        result = collect_detail_seed_urls(db, DEFAULT_DETAIL_SEEDS, snapshot_dir, active_only=config.active_only)
        total_new += result.new_count
        total_updated += result.updated_count
        total_success += result.success_count
        total_failure += result.failure_count
        failures.extend(result.failures)
    if config.use_similar_discovery:
        result = discover_similar_detail_pages(db, snapshot_dir, project_root, active_only=config.active_only)
        total_new += result.new_count
        total_updated += result.updated_count
        total_success += result.success_count
        total_failure += result.failure_count
        failures.extend(result.failures)
    if config.use_keyword_search:
        result = collect_from_search(db, DEFAULT_SEARCH_QUERIES, snapshot_dir, max_results_per_query=3)
        total_new += result.new_count
        total_updated += result.updated_count
        total_success += result.success_count
        total_failure += result.failure_count
        failures.extend(result.failures)
    after_df = db.df("tasks")
    after_completeness = 0.0 if after_df.empty else round(sum(field_completeness(row) for row in after_df.to_dict("records")) / len(after_df), 2)
    feasibility = [analyze_task(row).feasibility for row in after_df.to_dict("records")]
    record = {
        "created_at": datetime.now().replace(microsecond=0).isoformat(),
        "new_count": total_new,
        "updated_count": total_updated,
        "success_count": total_success,
        "failure_count": total_failure,
        "failures": failures,
        "recommended_count": feasibility.count("推荐做"),
        "doable_count": feasibility.count("可以做"),
        "field_completeness_before": before_completeness,
        "field_completeness_after": after_completeness,
    }
    db.log_run("auto_collect", "local_runtime_schedule", "ok" if total_success or not total_failure else "blocked", "; ".join(failures), total_success, total_failure, total_new, total_updated)
    return record

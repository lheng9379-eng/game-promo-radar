from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Iterable

import duckdb
import pandas as pd

from .models import Task, TaskNote, now_iso
from .rules import is_missing


def _clean_log_text(value: str | None) -> str:
    if is_missing(value):
        return ""
    text = str(value)
    if "????" in text:
        return "编码异常内容（原日志疑似乱码）"
    return text


TASK_COLUMNS = [
    "dedupe_key",
    "platform",
    "game_name",
    "task_name",
    "page_title",
    "reward_description",
    "task_id",
    "task_type",
    "billing_method",
    "unit_price",
    "revenue_share",
    "start_time",
    "deadline",
    "account_requirements",
    "material_url",
    "production_requirements",
    "requires_real_person",
    "requires_original_shooting",
    "requires_complex_editing",
    "public_heat_clues",
    "competition_clues",
    "candidate_links",
    "image_paths",
    "ocr_text",
    "ocr_status",
    "value_keywords",
    "signup_url",
    "source_url",
    "first_seen_at",
    "last_updated_at",
    "last_seen_at",
    "raw_snapshot",
    "confidence",
]


class RadarDB:
    def __init__(self, path: str | Path = "data/game_promo_radar.duckdb") -> None:
        self.path = self._prepare_db_path(Path(path))
        self.con = duckdb.connect(str(self.path))
        self.init_schema()

    @staticmethod
    def _prepare_db_path(path: Path) -> Path:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            probe = path.parent / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return path
        except OSError:
            fallback_dir = Path(tempfile.gettempdir()) / "game_promo_radar"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            return fallback_dir / path.name

    def init_schema(self) -> None:
        self.con.execute(
            """
            create table if not exists tasks (
              dedupe_key varchar primary key,
              platform varchar,
              game_name varchar,
              task_name varchar,
              page_title varchar,
              reward_description varchar,
              task_id varchar,
              task_type varchar,
              billing_method varchar,
              unit_price double,
              revenue_share double,
              start_time varchar,
              deadline varchar,
              account_requirements varchar,
              material_url varchar,
              production_requirements varchar,
              requires_real_person boolean,
              requires_original_shooting boolean,
              requires_complex_editing boolean,
              public_heat_clues varchar,
              competition_clues varchar,
              candidate_links varchar,
              image_paths varchar,
              ocr_text varchar,
              ocr_status varchar,
              value_keywords varchar,
              signup_url varchar,
              source_url varchar,
              first_seen_at varchar,
              last_updated_at varchar,
              last_seen_at varchar,
              raw_snapshot varchar,
              confidence double
            )
            """
        )
        self.con.execute("alter table tasks add column if not exists last_seen_at varchar")
        self.con.execute("alter table tasks add column if not exists page_title varchar")
        self.con.execute("alter table tasks add column if not exists reward_description varchar")
        self.con.execute("alter table tasks add column if not exists requires_real_person boolean")
        self.con.execute("alter table tasks add column if not exists requires_original_shooting boolean")
        self.con.execute("alter table tasks add column if not exists requires_complex_editing boolean")
        self.con.execute("alter table tasks add column if not exists public_heat_clues varchar")
        self.con.execute("alter table tasks add column if not exists competition_clues varchar")
        self.con.execute("alter table tasks add column if not exists candidate_links varchar")
        self.con.execute("alter table tasks add column if not exists image_paths varchar")
        self.con.execute("alter table tasks add column if not exists ocr_text varchar")
        self.con.execute("alter table tasks add column if not exists ocr_status varchar")
        self.con.execute("alter table tasks add column if not exists value_keywords varchar")
        self.con.execute(
            """
            create table if not exists task_notes (
              task_dedupe_key varchar,
              note varchar,
              created_at varchar
            )
            """
        )
        self.con.execute(
            """
            create table if not exists crawl_runs (
              source_key varchar,
              source_url varchar,
              status varchar,
              message varchar,
              success_count integer,
              failure_count integer,
              new_count integer,
              updated_count integer,
              created_at varchar
            )
            """
        )
        self.con.execute("alter table crawl_runs add column if not exists success_count integer")
        self.con.execute("alter table crawl_runs add column if not exists failure_count integer")
        self.con.execute("alter table crawl_runs add column if not exists new_count integer")
        self.con.execute("alter table crawl_runs add column if not exists updated_count integer")
        self.con.execute(
            """
            update crawl_runs
            set message = '编码异常内容（原日志疑似乱码）'
            where message is not null and regexp_matches(message, '\\?{4,}')
            """
        )
        self.con.execute(
            """
            create table if not exists opportunity_heat_metrics (
              task_dedupe_key varchar,
              game_search_keyword varchar,
              heat_source varchar,
              heat_index double,
              heat_rank integer,
              heat_trend varchar,
              heat_snapshot_time varchar,
              heat_source_url varchar,
              heat_notes varchar,
              intel_status varchar,
              created_at varchar
            )
            """
        )
        self.con.execute("alter table opportunity_heat_metrics add column if not exists intel_status varchar")
        self.con.execute(
            """
            create table if not exists opportunity_app_ranks (
              task_dedupe_key varchar,
              app_rank_source varchar,
              app_store_platform varchar,
              app_rank_category varchar,
              app_rank_position integer,
              app_rank_change integer,
              app_rating double,
              app_review_count integer,
              app_download_text varchar,
              app_rank_snapshot_time varchar,
              app_rank_source_url varchar,
              intel_status varchar,
              created_at varchar
            )
            """
        )
        self.con.execute("alter table opportunity_app_ranks add column if not exists intel_status varchar")
        self.con.execute(
            """
            create table if not exists opportunity_ad_intel (
              task_dedupe_key varchar,
              ad_intel_source varchar,
              ad_material_count integer,
              ad_active_days integer,
              ad_platforms varchar,
              ad_creative_keywords varchar,
              ad_landing_type varchar,
              ad_trend varchar,
              ad_snapshot_time varchar,
              ad_source_url varchar,
              intel_status varchar,
              created_at varchar
            )
            """
        )
        self.con.execute("alter table opportunity_ad_intel add column if not exists intel_status varchar")
        self.con.execute(
            """
            create table if not exists opportunity_sample_videos (
              task_dedupe_key varchar,
              sample_platform varchar,
              sample_keyword varchar,
              sample_video_title varchar,
              sample_author_name varchar,
              sample_publish_time varchar,
              sample_like_count integer,
              sample_comment_count integer,
              sample_collect_count integer,
              sample_share_count integer,
              sample_view_count integer,
              sample_video_duration varchar,
              sample_content_type varchar,
              sample_hook_text varchar,
              sample_source_url varchar,
              sample_snapshot_time varchar,
              intel_status varchar,
              created_at varchar
            )
            """
        )
        self.con.execute("alter table opportunity_sample_videos add column if not exists intel_status varchar")
        self.con.execute("create unique index if not exists idx_sample_video_unique on opportunity_sample_videos(task_dedupe_key, sample_source_url)")
        self.con.execute(
            """
            create table if not exists opportunity_material_assets (
              task_dedupe_key varchar,
              material_pack_url varchar,
              has_official_material boolean,
              has_video_material boolean,
              has_image_material boolean,
              has_bgm boolean,
              has_script_template boolean,
              has_gameplay_recording boolean,
              material_auth_scope varchar,
              material_download_status varchar,
              material_notes varchar,
              intel_status varchar,
              updated_at varchar
            )
            """
        )
        self.con.execute("alter table opportunity_material_assets add column if not exists intel_status varchar")
        self.con.execute("create unique index if not exists idx_material_unique on opportunity_material_assets(task_dedupe_key, material_pack_url)")
        self.con.execute(
            """
            create table if not exists opportunity_risk_signals (
              task_dedupe_key varchar,
              copyright_risk varchar,
              settlement_risk varchar,
              content_risk varchar,
              task_removed_flag boolean,
              negative_feedback_count integer,
              risk_keywords varchar,
              risk_notes varchar,
              risk_level varchar,
              intel_status varchar,
              updated_at varchar
            )
            """
        )
        self.con.execute("alter table opportunity_risk_signals add column if not exists risk_level varchar")
        self.con.execute("alter table opportunity_risk_signals add column if not exists intel_status varchar")
        self.con.execute("create unique index if not exists idx_risk_unique on opportunity_risk_signals(task_dedupe_key)")
        self.con.execute(
            """
            create table if not exists opportunity_intel_links (
              task_dedupe_key varchar,
              intel_type varchar,
              source_platform varchar,
              source_url varchar,
              page_title varchar,
              page_summary varchar,
              snapshot_path varchar,
              extracted_task_name varchar,
              extracted_game_name varchar,
              extracted_reward varchar,
              extracted_deadline varchar,
              extracted_requirements varchar,
              extracted_risk varchar,
              extracted_fields_json varchar,
              intel_status varchar,
              notes varchar,
              created_at varchar,
              updated_at varchar
            )
            """
        )
        for column in [
            "extracted_task_name varchar",
            "extracted_game_name varchar",
            "extracted_reward varchar",
            "extracted_deadline varchar",
            "extracted_requirements varchar",
            "extracted_risk varchar",
            "extracted_fields_json varchar",
        ]:
            self.con.execute(f"alter table opportunity_intel_links add column if not exists {column}")
        self.con.execute("create unique index if not exists idx_intel_link_unique on opportunity_intel_links(task_dedupe_key, source_url)")
        self.con.execute(
            """
            create table if not exists opportunity_unlinked_intel (
              id varchar primary key,
              source_url varchar,
              page_title varchar,
              page_summary varchar,
              snapshot_path varchar,
              source_platform varchar,
              extracted_task_name varchar,
              extracted_game_name varchar,
              extracted_reward varchar,
              extracted_deadline varchar,
              extracted_requirements varchar,
              extracted_risk varchar,
              extracted_fields_json varchar,
              linked_task_dedupe_key varchar,
              intel_status varchar,
              created_at varchar,
              updated_at varchar
            )
            """
        )
        self.con.execute("create unique index if not exists idx_unlinked_intel_source_url on opportunity_unlinked_intel(source_url)")
        # Kept for backward compatibility with existing local data. New UI uses task_notes.
        self.con.execute(
            """
            create table if not exists settlements (
              task_dedupe_key varchar,
              video_url varchar,
              published_at varchar,
              valid_views integer,
              clicks integer,
              downloads integer,
              activations integer,
              registrations integer,
              recharge_amount double,
              estimated_income double,
              actual_settlement double,
              settlement_date varchar,
              "variance" double
            )
            """
        )

    def _task_row(self, dedupe_key: str) -> dict | None:
        row = self.con.execute("select * from tasks where dedupe_key = ?", [dedupe_key]).fetchone()
        if not row:
            return None
        cols = [desc[0] for desc in self.con.description]
        return dict(zip(cols, row))

    def _merge_task_record(self, old: dict, new: dict, seen_at: str) -> dict:
        merged = old.copy()
        for key, value in new.items():
            if key in {"dedupe_key", "first_seen_at", "last_updated_at", "last_seen_at"}:
                continue
            if not is_missing(value):
                merged[key] = value
        merged["dedupe_key"] = old["dedupe_key"]
        merged["first_seen_at"] = old.get("first_seen_at") or new.get("first_seen_at") or seen_at
        merged["last_seen_at"] = seen_at
        merged["last_updated_at"] = seen_at
        return merged

    def _insert_task_record(self, rec: dict) -> None:
        values = [rec.get(col) for col in TASK_COLUMNS]
        placeholders = ", ".join(["?"] * len(TASK_COLUMNS))
        columns = ", ".join(TASK_COLUMNS)
        self.con.execute(
            f"insert into tasks ({columns}) values ({placeholders})",
            values,
        )

    def _update_task_record(self, rec: dict) -> None:
        update_columns = [col for col in TASK_COLUMNS if col != "dedupe_key"]
        assignments = ", ".join(f"{col} = ?" for col in update_columns)
        values = [rec.get(col) for col in update_columns]
        values.append(rec["dedupe_key"])
        self.con.execute(
            f"update tasks set {assignments} where dedupe_key = ?",
            values,
        )

    def upsert_task(self, task: Task) -> str:
        rec = task.to_record()
        seen_at = now_iso()
        existing = self._task_row(rec["dedupe_key"])
        if existing:
            self._update_task_record(self._merge_task_record(existing, rec, seen_at))
            return "updated"
        rec["first_seen_at"] = rec.get("first_seen_at") or seen_at
        rec["last_seen_at"] = seen_at
        rec["last_updated_at"] = seen_at
        self._insert_task_record(rec)
        return "new"

    def upsert_tasks(self, tasks: Iterable[Task]) -> int:
        count = 0
        for task in tasks:
            self.upsert_task(task)
            count += 1
        return count

    def add_task_note(self, note: TaskNote) -> None:
        self.con.execute(
            "insert into task_notes values (?, ?, ?)",
            [note.task_dedupe_key, note.note, note.created_at],
        )

    def log_run(
        self,
        source_key: str,
        source_url: str,
        status: str,
        message: str,
        success_count: int = 0,
        failure_count: int = 0,
        new_count: int = 0,
        updated_count: int = 0,
    ) -> None:
        self.con.execute(
            """
            insert into crawl_runs (
              source_key, source_url, status, message,
              success_count, failure_count, new_count, updated_count, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                _clean_log_text(source_key),
                _clean_log_text(source_url),
                _clean_log_text(status),
                _clean_log_text(message),
                success_count,
                failure_count,
                new_count,
                updated_count,
                now_iso(),
            ],
        )

    def df(self, table: str) -> pd.DataFrame:
        allowed = {
            "tasks",
            "task_notes",
            "crawl_runs",
            "settlements",
            "opportunity_heat_metrics",
            "opportunity_app_ranks",
            "opportunity_ad_intel",
            "opportunity_sample_videos",
            "opportunity_material_assets",
            "opportunity_risk_signals",
            "opportunity_intel_links",
            "opportunity_unlinked_intel",
        }
        if table not in allowed:
            raise ValueError(f"unsupported table: {table}")
        return self.con.execute(f"select * from {table}").df()

    def insert_record(self, table: str, record: dict) -> None:
        allowed = {
            "opportunity_heat_metrics",
            "opportunity_app_ranks",
            "opportunity_ad_intel",
            "opportunity_sample_videos",
            "opportunity_material_assets",
            "opportunity_risk_signals",
            "opportunity_intel_links",
            "opportunity_unlinked_intel",
        }
        if table not in allowed:
            raise ValueError(f"unsupported table: {table}")
        table_cols = {row[1] for row in self.con.execute(f"pragma table_info('{table}')").fetchall()}
        rec = {key: value for key, value in record.items() if key in table_cols and not is_missing(value)}
        rec.setdefault("created_at", now_iso())
        if table in {"opportunity_material_assets", "opportunity_risk_signals"}:
            rec.setdefault("updated_at", now_iso())
            rec.pop("created_at", None)
        cols = list(rec.keys())
        placeholders = ", ".join(["?"] * len(cols))
        self.con.execute(f"insert into {table} ({', '.join(cols)}) values ({placeholders})", [rec[col] for col in cols])

    def upsert_sample_video(self, record: dict) -> None:
        if is_missing(record.get("task_dedupe_key")) or is_missing(record.get("sample_source_url")):
            return
        existing = self.con.execute(
            """
            select 1 from opportunity_sample_videos
            where task_dedupe_key = ? and sample_source_url = ?
            """,
            [record.get("task_dedupe_key"), record.get("sample_source_url")],
        ).fetchone()
        if existing:
            return
        self.insert_record("opportunity_sample_videos", record)

    def upsert_latest_record(self, table: str, key_columns: list[str], record: dict) -> None:
        table_cols = {row[1] for row in self.con.execute(f"pragma table_info('{table}')").fetchall()}
        where = " and ".join(f"{col} = ?" for col in key_columns)
        values = [record.get(col) for col in key_columns]
        existing = self.con.execute(f"select 1 from {table} where {where}", values).fetchone()
        if existing:
            rec = {key: value for key, value in record.items() if key in table_cols and key not in key_columns and not is_missing(value)}
            rec["updated_at"] = now_iso()
            assignments = ", ".join(f"{col} = ?" for col in rec)
            self.con.execute(f"update {table} set {assignments} where {where}", list(rec.values()) + values)
            return
        self.insert_record(table, record)

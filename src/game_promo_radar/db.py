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
        self.con.execute("alter table crawl_runs add column if not exists retry_after varchar")
        self.con.execute("alter table crawl_runs add column if not exists login_state varchar")
        self.con.execute(
            """
            create table if not exists data_sources (
              source_id varchar primary key,
              source_name varchar,
              source_type varchar,
              content_platform varchar,
              base_url varchar,
              discovery_method varchar,
              login_required boolean,
              parser_name varchar,
              crawl_frequency varchar,
              enabled boolean,
              reliability_level varchar,
              last_success_at varchar,
              last_error varchar,
              consecutive_failures integer
            )
            """
        )
        for column in [
            "source_id varchar",
            "source_name varchar",
            "source_type varchar",
            "content_platform varchar",
            "base_url varchar",
            "discovery_method varchar",
            "login_required boolean",
            "parser_name varchar",
            "crawl_frequency varchar",
            "enabled boolean",
            "reliability_level varchar",
            "last_success_at varchar",
            "last_error varchar",
            "consecutive_failures integer",
        ]:
            self.con.execute(f"alter table data_sources add column if not exists {column}")
        self.con.execute(
            """
            create table if not exists campaign_candidates (
              candidate_id varchar primary key,
              source_id varchar,
              source_platform varchar,
              content_platform varchar,
              publisher_name varchar,
              publisher_type varchar,
              campaign_name varchar,
              campaign_type varchar,
              source_url varchar,
              registration_url varchar,
              reward_model varchar,
              reward_min double,
              reward_max double,
              reward_pool double,
              account_requirements varchar,
              publish_requirements varchar,
              material_requirements varchar,
              deadline varchar,
              source_reliability varchar,
              risk_level varchar,
              status varchar,
              validation_notes varchar,
              risk_signals varchar,
              raw_text varchar,
              raw_snapshot varchar,
              discovered_at varchar,
              last_verified_at varchar,
              merged_into_campaign_id varchar
            )
            """
        )
        self.con.execute("create unique index if not exists idx_campaign_candidates_url on campaign_candidates(source_url)")
        self.con.execute(
            """
            create table if not exists campaigns (
              campaign_id varchar primary key,
              content_platform varchar,
              source_platform varchar,
              publisher_name varchar,
              publisher_type varchar,
              campaign_name varchar,
              campaign_type varchar,
              source_url varchar,
              registration_url varchar,
              reward_model varchar,
              reward_min double,
              reward_max double,
              reward_pool double,
              guaranteed_reward double,
              tiered_reward varchar,
              view_based_settlement varchar,
              win_probability double,
              shortlist_probability double,
              expected_income double,
              estimated_production_hours double,
              expected_hourly_income double,
              account_requirements varchar,
              publish_requirements varchar,
              material_requirements varchar,
              deadline varchar,
              source_reliability varchar,
              risk_level varchar,
              recommendation varchar,
              score double,
              score_reasons varchar,
              discovered_at varchar,
              last_verified_at varchar,
              status varchar,
              raw_text varchar,
              raw_snapshot varchar
            )
            """
        )
        self.con.execute("create unique index if not exists idx_campaigns_source_url on campaigns(source_url)")
        self.con.execute(
            """
            create table if not exists campaign_progress (
              campaign_id varchar,
              status varchar,
              signup_at varchar,
              work_url varchar,
              published_at varchar,
              view_count integer,
              like_count integer,
              comment_count integer,
              final_settlement_amount double,
              settled_at varchar,
              actual_production_hours double,
              actual_hourly_income double,
              notes varchar,
              updated_at varchar
            )
            """
        )
        self.con.execute(
            """
            create table if not exists discovery_records (
              record_id varchar primary key,
              source_id varchar,
              discovery_method varchar,
              query varchar,
              title varchar,
              snippet varchar,
              source_url varchar,
              detail_status varchar,
              filter_status varchar,
              filter_reason varchar,
              raw_text varchar,
              raw_snapshot varchar,
              discovered_at varchar,
              candidate_id varchar
            )
            """
        )
        self.con.execute("create unique index if not exists idx_discovery_records_url on discovery_records(source_url)")
        self.con.execute(
            """
            create table if not exists source_discovery_candidates (
              domain varchar primary key,
              source_name_guess varchar,
              first_seen_at varchar,
              last_seen_at varchar,
              discovered_campaign_count integer,
              valid_campaign_count integer,
              reliability_guess varchar,
              example_urls varchar,
              status varchar
            )
            """
        )
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
            "data_sources",
            "campaign_candidates",
            "campaigns",
            "campaign_progress",
            "discovery_records",
            "source_discovery_candidates",
        }
        if table not in allowed:
            raise ValueError(f"unsupported table: {table}")
        return self.con.execute(f"select * from {table}").df()

    def upsert_data_source(self, record: dict) -> None:
        rec = record.copy()
        rec.setdefault("consecutive_failures", 0)
        columns = [row[1] for row in self.con.execute("pragma table_info('data_sources')").fetchall()]
        legacy_defaults = {
            "source_key": rec.get("source_id"),
            "name": rec.get("source_name"),
            "platform": rec.get("content_platform"),
            "task_category": "campaign",
            "collection_method": rec.get("discovery_method"),
            "link": rec.get("base_url"),
            "frequency": rec.get("crawl_frequency"),
            "notes": rec.get("source_type"),
        }
        for key, value in legacy_defaults.items():
            if key in columns and key not in rec:
                rec[key] = value
        rec = {key: rec.get(key) for key in columns if key in rec}
        existing = self.con.execute("select 1 from data_sources where source_id = ?", [rec.get("source_id")]).fetchone()
        if existing:
            update_columns = [col for col in rec if col != "source_id"]
            assignments = ", ".join(f"{col} = ?" for col in update_columns)
            self.con.execute(
                f"update data_sources set {assignments} where source_id = ?",
                [rec[col] for col in update_columns] + [rec["source_id"]],
            )
            return
        columns = list(rec.keys())
        placeholders = ", ".join(["?"] * len(columns))
        self.con.execute(
            f"insert into data_sources ({', '.join(columns)}) values ({placeholders})",
            [rec[col] for col in columns],
        )

    def upsert_campaign_candidate(self, record: dict) -> str:
        rec = record.copy()
        rec.setdefault("discovered_at", now_iso())
        rec.setdefault("status", "待验证")
        columns = [row[1] for row in self.con.execute("pragma table_info('campaign_candidates')").fetchall()]
        rec = {key: rec.get(key) for key in columns if key in rec}
        existing = self.con.execute("select * from campaign_candidates where candidate_id = ?", [rec.get("candidate_id")]).fetchone()
        if not existing and rec.get("source_url"):
            existing = self.con.execute("select * from campaign_candidates where source_url = ?", [rec.get("source_url")]).fetchone()
        if existing:
            update_columns = [col for col in rec if col != "candidate_id" and rec.get(col) is not None]
            assignments = ", ".join(f"{col} = ?" for col in update_columns)
            key = existing[0]
            self.con.execute(
                f"update campaign_candidates set {assignments} where candidate_id = ?",
                [rec[col] for col in update_columns] + [key],
            )
            return "updated"
        columns = list(rec.keys())
        placeholders = ", ".join(["?"] * len(columns))
        self.con.execute(
            f"insert into campaign_candidates ({', '.join(columns)}) values ({placeholders})",
            [rec[col] for col in columns],
        )
        return "new"

    def upsert_campaign(self, record: dict) -> str:
        rec = record.copy()
        rec.setdefault("status", "有效")
        rec.setdefault("last_verified_at", now_iso())
        columns = [row[1] for row in self.con.execute("pragma table_info('campaigns')").fetchall()]
        rec = {key: rec.get(key) for key in columns if key in rec}
        existing = self.con.execute("select 1 from campaigns where campaign_id = ?", [rec.get("campaign_id")]).fetchone()
        if not existing and rec.get("source_url"):
            existing = self.con.execute("select 1 from campaigns where source_url = ?", [rec.get("source_url")]).fetchone()
        if existing:
            update_columns = [col for col in rec if col != "campaign_id" and rec.get(col) is not None]
            assignments = ", ".join(f"{col} = ?" for col in update_columns)
            self.con.execute(
                f"update campaigns set {assignments} where campaign_id = ?",
                [rec[col] for col in update_columns] + [rec["campaign_id"]],
            )
            return "updated"
        columns = list(rec.keys())
        placeholders = ", ".join(["?"] * len(columns))
        self.con.execute(f"insert into campaigns ({', '.join(columns)}) values ({placeholders})", [rec[col] for col in columns])
        return "new"

    def upsert_discovery_record(self, record: dict) -> str:
        rec = record.copy()
        rec.setdefault("discovered_at", now_iso())
        columns = [row[1] for row in self.con.execute("pragma table_info('discovery_records')").fetchall()]
        rec = {key: rec.get(key) for key in columns if key in rec}
        existing = self.con.execute("select * from discovery_records where record_id = ?", [rec.get("record_id")]).fetchone()
        if not existing and rec.get("source_url"):
            existing = self.con.execute("select * from discovery_records where source_url = ?", [rec.get("source_url")]).fetchone()
        if existing:
            update_columns = [col for col in rec if col != "record_id" and rec.get(col) is not None]
            assignments = ", ".join(f"{col} = ?" for col in update_columns)
            self.con.execute(
                f"update discovery_records set {assignments} where record_id = ?",
                [rec[col] for col in update_columns] + [existing[0]],
            )
            return "updated"
        columns = list(rec.keys())
        placeholders = ", ".join(["?"] * len(columns))
        self.con.execute(
            f"insert into discovery_records ({', '.join(columns)}) values ({placeholders})",
            [rec[col] for col in columns],
        )
        return "new"

    def upsert_source_discovery_candidate(self, record: dict) -> None:
        rec = record.copy()
        rec.setdefault("first_seen_at", now_iso())
        rec.setdefault("last_seen_at", now_iso())
        rec.setdefault("status", "待确认")
        rec.setdefault("discovered_campaign_count", 0)
        rec.setdefault("valid_campaign_count", 0)
        columns = [row[1] for row in self.con.execute("pragma table_info('source_discovery_candidates')").fetchall()]
        rec = {key: rec.get(key) for key in columns if key in rec}
        existing = self.con.execute("select * from source_discovery_candidates where domain = ?", [rec.get("domain")]).fetchone()
        if existing:
            update_columns = [col for col in rec if col not in {"domain", "first_seen_at"} and rec.get(col) is not None]
            assignments = ", ".join(f"{col} = ?" for col in update_columns)
            self.con.execute(
                f"update source_discovery_candidates set {assignments} where domain = ?",
                [rec[col] for col in update_columns] + [rec["domain"]],
            )
            return
        columns = list(rec.keys())
        placeholders = ", ".join(["?"] * len(columns))
        self.con.execute(
            f"insert into source_discovery_candidates ({', '.join(columns)}) values ({placeholders})",
            [rec[col] for col in columns],
        )

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

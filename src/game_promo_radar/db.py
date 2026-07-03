from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Iterable

import duckdb
import pandas as pd

from .models import AccountProfile, DataSource, ImportRun, Task, TaskNote, next_scheduled_time, now_iso

TASK_COLUMNS = [
    "dedupe_key",
    "platform",
    "game_name",
    "task_name",
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
    "signup_url",
    "source_url",
    "first_seen_at",
    "last_updated_at",
    "raw_snapshot",
    "confidence",
    "task_category",
    "settlement_type",
    "content_form",
    "target_account_type",
    "publish_platforms",
    "reward_rule_text",
    "risk_level",
    "difficulty_level",
    "expected_value_score",
    "account_match_score",
    "is_game_related",
]

EXTRA_TASK_COLUMNS = {
    "task_category": "varchar default 'game'",
    "settlement_type": "varchar default 'unknown'",
    "content_form": "varchar default 'short_video'",
    "target_account_type": "varchar",
    "publish_platforms": "varchar",
    "reward_rule_text": "varchar",
    "risk_level": "varchar",
    "difficulty_level": "integer",
    "expected_value_score": "integer",
    "account_match_score": "integer",
    "is_game_related": "boolean default true",
}

EXTRA_DATA_SOURCE_COLUMNS = {
    "next_scheduled_at": "varchar",
}


def _quote_identifier(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) + chr(34))}"'


def _quote_columns(columns: Iterable[str]) -> str:
    return ", ".join(_quote_identifier(column) for column in columns)


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
        statements = [
            """
            create table if not exists "tasks" (
              "dedupe_key" varchar primary key,
              "platform" varchar,
              "game_name" varchar,
              "task_name" varchar,
              "task_id" varchar,
              "task_type" varchar,
              "billing_method" varchar,
              "unit_price" double,
              "revenue_share" double,
              "start_time" varchar,
              "deadline" varchar,
              "account_requirements" varchar,
              "material_url" varchar,
              "production_requirements" varchar,
              "signup_url" varchar,
              "source_url" varchar,
              "first_seen_at" varchar,
              "last_updated_at" varchar,
              "raw_snapshot" varchar,
              "confidence" double,
              "task_category" varchar default 'game',
              "settlement_type" varchar default 'unknown',
              "content_form" varchar default 'short_video',
              "target_account_type" varchar,
              "publish_platforms" varchar,
              "reward_rule_text" varchar,
              "risk_level" varchar,
              "difficulty_level" integer,
              "expected_value_score" integer,
              "account_match_score" integer,
              "is_game_related" boolean default true
            )
            """,
            """
            create table if not exists "task_notes" (
              "task_dedupe_key" varchar,
              "note" varchar,
              "created_at" varchar
            )
            """,
            """
            create table if not exists "crawl_runs" (
              "source_key" varchar,
              "source_url" varchar,
              "status" varchar,
              "message" varchar,
              "created_at" varchar
            )
            """,
            """
            create table if not exists "account_profiles" (
              "profile_key" varchar primary key,
              "account_name" varchar,
              "platform" varchar,
              "account_domain" varchar,
              "follower_count" integer,
              "average_views" integer,
              "content_forms" varchar,
              "real_person" boolean,
              "acceptable_categories" varchar,
              "created_at" varchar,
              "updated_at" varchar
            )
            """,
            """
            create table if not exists "data_sources" (
              "source_key" varchar primary key,
              "name" varchar,
              "platform" varchar,
              "task_category" varchar,
              "collection_method" varchar,
              "link" varchar,
              "enabled" boolean,
              "frequency" varchar,
              "notes" varchar,
              "next_scheduled_at" varchar,
              "created_at" varchar,
              "updated_at" varchar
            )
            """,
            """
            create table if not exists "import_runs" (
              "source" varchar,
              "source_type" varchar,
              "success_count" integer,
              "failure_count" integer,
              "status" varchar,
              "error_reason" varchar,
              "created_at" varchar
            )
            """,
            """
            create table if not exists "settlements" (
              "task_dedupe_key" varchar,
              "video_url" varchar,
              "published_at" varchar,
              "valid_views" integer,
              "clicks" integer,
              "downloads" integer,
              "activations" integer,
              "registrations" integer,
              "recharge_amount" double,
              "estimated_income" double,
              "actual_settlement" double,
              "settlement_date" varchar,
              "variance" double
            )
            """,
        ]
        for statement in statements:
            self.con.execute(statement)
        self._ensure_task_columns()
        self._ensure_data_source_columns()

    def _ensure_task_columns(self) -> None:
        existing = {
            row[1]
            for row in self.con.execute('pragma table_info("tasks")').fetchall()
        }
        for column, definition in EXTRA_TASK_COLUMNS.items():
            if column not in existing:
                self.con.execute(
                    f"alter table {_quote_identifier('tasks')} add column {_quote_identifier(column)} {definition}"
                )

    def _ensure_data_source_columns(self) -> None:
        existing = {
            row[1]
            for row in self.con.execute('pragma table_info("data_sources")').fetchall()
        }
        for column, definition in EXTRA_DATA_SOURCE_COLUMNS.items():
            if column not in existing:
                self.con.execute(
                    f"alter table {_quote_identifier('data_sources')} add column {_quote_identifier(column)} {definition}"
                )

    def upsert_tasks(self, tasks: Iterable[Task]) -> int:
        count = 0
        for task in tasks:
            rec = task.to_record()
            existing = self.con.execute(
                'select "first_seen_at" from "tasks" where "dedupe_key" = ?', [rec["dedupe_key"]]
            ).fetchone()
            if existing:
                rec["first_seen_at"] = existing[0]
            rec["last_updated_at"] = now_iso()
            columns = _quote_columns(TASK_COLUMNS)
            placeholders = ", ".join(["?"] * len(TASK_COLUMNS))
            self.con.execute(
                f'insert or replace into "tasks" ({columns}) values ({placeholders})',
                [rec.get(column) for column in TASK_COLUMNS],
            )
            count += 1
        return count

    def add_task_note(self, note: TaskNote) -> None:
        self.con.execute(
            'insert into "task_notes" values (?, ?, ?)',
            [note.task_dedupe_key, note.note, note.created_at],
        )

    def upsert_account_profile(self, profile: AccountProfile) -> None:
        rec = profile.to_record()
        existing = self.con.execute(
            'select "created_at" from "account_profiles" where "profile_key" = ?',
            [rec["profile_key"]],
        ).fetchone()
        if existing:
            rec["created_at"] = existing[0]
        rec["updated_at"] = now_iso()
        self.con.execute(
            """
            insert or replace into "account_profiles" values (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                rec["profile_key"],
                rec["account_name"],
                rec["platform"],
                rec["account_domain"],
                rec["follower_count"],
                rec["average_views"],
                rec["content_forms"],
                rec["real_person"],
                rec["acceptable_categories"],
                rec["created_at"],
                rec["updated_at"],
            ],
        )

    def upsert_data_source(self, source: DataSource) -> None:
        rec = source.to_record()
        existing = self.con.execute(
            'select "created_at" from "data_sources" where "source_key" = ?',
            [rec["source_key"]],
        ).fetchone()
        if existing:
            rec["created_at"] = existing[0]
        rec["updated_at"] = now_iso()
        self.con.execute(
            """
            insert or replace into "data_sources" (
              "source_key", "name", "platform", "task_category", "collection_method", "link",
              "enabled", "frequency", "notes", "next_scheduled_at", "created_at", "updated_at"
            ) values (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                rec["source_key"],
                rec["name"],
                rec["platform"],
                rec["task_category"],
                rec["collection_method"],
                rec["link"],
                rec["enabled"],
                rec["frequency"],
                rec["notes"],
                rec["next_scheduled_at"],
                rec["created_at"],
                rec["updated_at"],
            ],
        )

    def set_data_source_enabled(self, source_key: str, enabled: bool) -> None:
        self.con.execute(
            'update "data_sources" set "enabled" = ?, "updated_at" = ? where "source_key" = ?',
            [enabled, now_iso(), source_key],
        )

    def mark_data_source_collected(self, source_key: str, frequency: str) -> None:
        self.con.execute(
            'update "data_sources" set "next_scheduled_at" = ?, "updated_at" = ? where "source_key" = ?',
            [next_scheduled_time(frequency), now_iso(), source_key],
        )

    def log_import_run(self, run: ImportRun) -> None:
        self.con.execute(
            'insert into "import_runs" values (?, ?, ?, ?, ?, ?, ?)',
            [
                run.source,
                run.source_type,
                run.success_count,
                run.failure_count,
                run.status,
                run.error_reason,
                run.created_at,
            ],
        )

    def log_run(
        self,
        source_key: str,
        source_url: str,
        status: str,
        message: str,
        success_count: int = 0,
        failure_count: int | None = None,
    ) -> None:
        self.con.execute(
            'insert into "crawl_runs" values (?, ?, ?, ?, ?)',
            [source_key, source_url, status, message, now_iso()],
        )
        self.log_import_run(
            ImportRun(
                source=source_key,
                source_type="crawl",
                success_count=success_count,
                failure_count=(0 if status == "ok" else 1) if failure_count is None else failure_count,
                status=status,
                error_reason=message or None,
            )
        )

    def df(self, table: str) -> pd.DataFrame:
        allowed = {
            "tasks",
            "task_notes",
            "crawl_runs",
            "settlements",
            "account_profiles",
            "data_sources",
            "import_runs",
        }
        if table not in allowed:
            raise ValueError(f"unsupported table: {table}")
        return self.con.execute(f"select * from {_quote_identifier(table)}").df()

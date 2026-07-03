from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re
from typing import Any

TASK_TYPES = {"CPM", "CPA", "CPS", "CPT", "奖金活动", "普通创作激励"}
TASK_CATEGORIES = {
    "game",
    "app",
    "ecommerce",
    "local_life",
    "short_drama",
    "brand",
    "platform_incentive",
    "other",
}
SETTLEMENT_TYPES = {
    "play_count",
    "interaction",
    "download",
    "lead",
    "sale_commission",
    "fixed_reward",
    "traffic_support",
    "unknown",
}
CONTENT_FORMS = {"short_video", "note", "live", "image_text", "mixed"}
RISK_LEVELS = {"low", "medium", "high"}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def normalize_key_part(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


@dataclass
class Task:
    platform: str
    game_name: str
    task_name: str
    source_url: str
    task_category: str = "game"
    settlement_type: str = "unknown"
    content_form: str = "short_video"
    target_account_type: str | None = None
    publish_platforms: str | None = None
    reward_rule_text: str | None = None
    risk_level: str | None = None
    difficulty_level: int | None = None
    expected_value_score: int | None = None
    account_match_score: int | None = None
    is_game_related: bool = True
    task_id: str | None = None
    task_type: str = "普通创作激励"
    billing_method: str | None = None
    unit_price: float | None = None
    revenue_share: float | None = None
    start_time: str | None = None
    deadline: str | None = None
    account_requirements: str | None = None
    material_url: str | None = None
    production_requirements: str | None = None
    signup_url: str | None = None
    first_seen_at: str = field(default_factory=now_iso)
    last_updated_at: str = field(default_factory=now_iso)
    raw_snapshot: str | None = None
    confidence: float = 0.5

    def normalized_type(self) -> str:
        return self.task_type if self.task_type in TASK_TYPES else "普通创作激励"

    def normalized_category(self) -> str:
        return self.task_category if self.task_category in TASK_CATEGORIES else "other"

    def normalized_settlement_type(self) -> str:
        return self.settlement_type if self.settlement_type in SETTLEMENT_TYPES else "unknown"

    def normalized_content_form(self) -> str:
        return self.content_form if self.content_form in CONTENT_FORMS else "mixed"

    def normalized_risk_level(self) -> str | None:
        if self.risk_level is None:
            return None
        return self.risk_level if self.risk_level in RISK_LEVELS else "medium"

    def dedupe_key(self) -> str:
        if self.task_id:
            return f"{self.platform}|id|{self.task_id}".lower()
        if normalize_key_part(self.source_url):
            return "|".join(normalize_key_part(part) for part in [self.platform, self.source_url])
        parts = [
            self.platform,
            self.task_name,
            self.reward_rule_text,
        ]
        return "|".join(normalize_key_part(part) for part in parts)

    def to_record(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["task_type"] = self.normalized_type()
        data["task_category"] = self.normalized_category()
        data["settlement_type"] = self.normalized_settlement_type()
        data["content_form"] = self.normalized_content_form()
        data["risk_level"] = self.normalized_risk_level()
        data["dedupe_key"] = self.dedupe_key()
        return data


@dataclass
class TaskNote:
    task_dedupe_key: str
    note: str
    created_at: str = field(default_factory=now_iso)


@dataclass
class AccountProfile:
    account_name: str
    platform: str
    account_domain: str
    follower_count: int = 0
    average_views: int = 0
    content_forms: str | None = None
    real_person: bool = False
    acceptable_categories: str | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def profile_key(self) -> str:
        return f"{self.platform}|{self.account_name}".lower()

    def to_record(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["profile_key"] = self.profile_key()
        return data


@dataclass
class DataSource:
    name: str
    platform: str
    task_category: str
    collection_method: str
    link: str | None = None
    enabled: bool = True
    frequency: str = "manual"
    notes: str | None = None
    next_scheduled_at: str | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def source_key(self) -> str:
        return f"{self.platform}|{self.name}|{self.link or ''}".lower()

    def to_record(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["source_key"] = self.source_key()
        if not data.get("next_scheduled_at"):
            data["next_scheduled_at"] = next_scheduled_time(self.frequency)
        return data


@dataclass
class ImportRun:
    source: str
    source_type: str
    success_count: int
    failure_count: int = 0
    status: str = "ok"
    error_reason: str | None = None
    created_at: str = field(default_factory=now_iso)


def next_scheduled_time(frequency: str) -> str | None:
    now = datetime.now().replace(microsecond=0)
    if frequency == "daily":
        return (now + timedelta(days=1)).isoformat()
    if frequency == "weekly":
        return (now + timedelta(days=7)).isoformat()
    return None

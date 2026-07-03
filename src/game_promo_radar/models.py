from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TASK_TYPES = {"CPM", "CPA", "CPS", "CPT", "奖金活动", "普通创作激励"}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def normalize_source_url(url: str) -> str:
    parts = urlsplit(str(url).strip())
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    query_items = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    query = urlencode(query_items)
    return urlunsplit((scheme, netloc, path, query, ""))


@dataclass
class Task:
    platform: str
    game_name: str | None
    task_name: str
    source_url: str
    page_title: str | None = None
    reward_description: str | None = None
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
    requires_real_person: bool | None = None
    requires_original_shooting: bool | None = None
    requires_complex_editing: bool | None = None
    public_heat_clues: str | None = None
    competition_clues: str | None = None
    candidate_links: str | None = None
    image_paths: str | None = None
    ocr_text: str | None = None
    ocr_status: str | None = None
    value_keywords: str | None = None
    signup_url: str | None = None
    first_seen_at: str = field(default_factory=now_iso)
    last_updated_at: str = field(default_factory=now_iso)
    raw_snapshot: str | None = None
    confidence: float = 0.5

    def normalized_type(self) -> str:
        return self.task_type if self.task_type in TASK_TYPES else "普通创作激励"

    def dedupe_key(self) -> str:
        if self.task_id:
            return f"{self.platform}|id|{self.task_id}".lower()
        return f"url|{normalize_source_url(self.source_url)}".lower()

    def to_record(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["task_type"] = self.normalized_type()
        data["dedupe_key"] = self.dedupe_key()
        return data


@dataclass
class TaskNote:
    task_dedupe_key: str
    note: str
    created_at: str = field(default_factory=now_iso)

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REQUIRED_SOURCE_FIELDS = {
    "source_id",
    "source_name",
    "source_type",
    "content_platform",
    "base_url",
    "discovery_method",
    "login_required",
    "parser_name",
    "crawl_frequency",
    "enabled",
    "reliability_level",
    "last_success_at",
    "last_error",
    "consecutive_failures",
}

SOURCE_TYPES = {
    "official_task_platform",
    "brand_or_game_site",
    "official_account_or_community",
    "search_engine",
    "manual",
    "logged_in_browser",
    "auto_discovered_candidate",
}


def load_platform_sources(path: str | Path = "PLATFORM_SOURCE_LIST.yaml") -> list[dict[str, Any]]:
    file = Path(path)
    data = yaml.safe_load(file.read_text(encoding="utf-8")) if file.exists() else {}
    sources = data.get("sources", data if isinstance(data, list) else [])
    return [normalize_source_record(item) for item in sources]


def normalize_source_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = {field: record.get(field) for field in REQUIRED_SOURCE_FIELDS}
    normalized["enabled"] = bool(normalized.get("enabled"))
    normalized["login_required"] = bool(normalized.get("login_required"))
    normalized["consecutive_failures"] = int(normalized.get("consecutive_failures") or 0)
    return normalized


def validate_source_config(sources: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, source in enumerate(sources, start=1):
        missing = sorted(field for field in REQUIRED_SOURCE_FIELDS if field not in source)
        if missing:
            errors.append(f"source #{index} missing fields: {', '.join(missing)}")
        source_id = str(source.get("source_id") or "")
        if not source_id:
            errors.append(f"source #{index} has empty source_id")
        elif source_id in seen:
            errors.append(f"duplicate source_id: {source_id}")
        seen.add(source_id)
        if source.get("source_type") not in SOURCE_TYPES:
            errors.append(f"{source_id} has unsupported source_type: {source.get('source_type')}")
        if source.get("reliability_level") not in {"A", "B", "C", "D", "E"}:
            errors.append(f"{source_id} has unsupported reliability_level: {source.get('reliability_level')}")
    return errors


def sync_sources_to_db(db, path: str | Path = "PLATFORM_SOURCE_LIST.yaml") -> list[dict[str, Any]]:
    sources = load_platform_sources(path)
    for source in sources:
        db.upsert_data_source(source)
    return sources

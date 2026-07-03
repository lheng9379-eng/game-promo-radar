from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from game_promo_radar.models import Task


class AdapterResult:
    def __init__(self, tasks: list[Task], status: str = "ok", message: str = "") -> None:
        self.tasks = tasks
        self.status = status
        self.message = message


class SourceAdapter(ABC):
    key: str
    name: str

    @abstractmethod
    def collect(self) -> AdapterResult:
        raise NotImplementedError


def save_snapshot(snapshot_dir: str | Path, source_key: str, content: str) -> str:
    path = Path(snapshot_dir)
    path.mkdir(parents=True, exist_ok=True)
    filename = f"{source_key}-{abs(hash(content))}.html"
    target = path / filename
    if not target.exists():
        target.write_text(content, encoding="utf-8")
    return str(target)


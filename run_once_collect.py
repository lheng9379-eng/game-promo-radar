from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from game_promo_radar.db import RadarDB
from game_promo_radar.scheduler import append_auto_run, load_auto_config, run_auto_collect


def main() -> int:
    db = RadarDB(ROOT / "data" / "game_promo_radar.duckdb")
    config = load_auto_config(ROOT / "data" / "auto_collect_config.json")
    record = run_auto_collect(db, config, ROOT / "data" / "snapshots", ROOT)
    append_auto_run(ROOT / "data" / "auto_collect_runs.json", record)
    print("一次性采集完成：")
    print(f"  新增任务：{record['new_count']}")
    print(f"  更新任务：{record['updated_count']}")
    print(f"  失败数量：{record['failure_count']}")
    print(f"  字段完整率：{record['field_completeness_before']} -> {record['field_completeness_after']}")
    return 0 if record["failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

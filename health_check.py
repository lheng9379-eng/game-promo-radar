from __future__ import annotations

from pathlib import Path
import json
import socket


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB_PATH = DATA / "game_promo_radar.duckdb"
CONFIG_PATH = DATA / "auto_collect_config.json"
RUNS_PATH = DATA / "auto_collect_runs.json"
PORT = 8503


def ok(message: str) -> None:
    print(f"[正常] {message}")


def warn(message: str) -> None:
    print(f"[注意] {message}")


def fail(message: str) -> None:
    print(f"[异常] {message}")


def port_open(host: str = "127.0.0.1", port: int = PORT, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main() -> int:
    status = 0
    if DB_PATH.exists():
        ok(f"数据库存在：{DB_PATH}")
    else:
        fail(f"数据库不存在：{DB_PATH}")
        status = 1

    if CONFIG_PATH.exists():
        ok(f"自动采集配置存在：{CONFIG_PATH}")
        try:
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            print(f"  启用状态：{'启用' if config.get('enabled') else '停用'}")
            print(f"  每日时间：{config.get('daily_time', '待确认')}")
        except Exception as exc:
            warn(f"配置文件读取失败：{exc}")
            status = 1
    else:
        warn(f"自动采集配置不存在：{CONFIG_PATH}")

    if RUNS_PATH.exists():
        try:
            runs = json.loads(RUNS_PATH.read_text(encoding="utf-8"))
            if runs:
                ok(f"最近一次自动采集：{runs[-1].get('created_at', '待确认')}")
            else:
                warn("自动采集记录为空。")
        except Exception as exc:
            warn(f"自动采集记录读取失败：{exc}")
            status = 1
    else:
        warn("暂无自动采集记录。")

    if port_open():
        ok(f"Streamlit 端口 {PORT} 可访问：http://localhost:{PORT}/")
    else:
        warn(f"Streamlit 端口 {PORT} 当前未启动，请运行 start.bat。项目未启动时出现此提示是正常的。")

    return status


if __name__ == "__main__":
    raise SystemExit(main())

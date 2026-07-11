# Sync Diff Report

Generated: 2026-07-11 Asia/Shanghai

## Compared Paths
- D development directory: `D:\CodexProjects\game-promo-radar`
- C Git repository: `C:\Users\Laptop\Documents\游戏推广商机雷达`

## Ignore Rules
Ignored: `.git`, `.venv`, `__pycache__`, `.pytest_cache`, local `data/` runtime files, DuckDB/WAL files, logs, snapshots, screenshots, browser profiles, and pyc caches.

## 1. Files Only In D
- None

## 2. Files Only In C
- `.devcontainer/devcontainer.json`
- `SYNC_DIFF_REPORT.md`

## 3. Files Present In Both But Different
- None

## 4. Test File Differences
- None

## 5. Database Schema Code Difference
- `src/game_promo_radar/db.py` content equal after sync: `True`
- C schema contains `data_sources`: `True`
- C schema contains `campaign_candidates`: `True`
- C schema contains `campaigns`: `True`
- C schema contains `campaign_progress`: `True`
- C schema contains `retry_after`: `True`
- C schema contains `login_state`: `True`
- Cloud writable-path fallback `_prepare_db_path`: `True`

## 6. Streamlit Page Difference
- `app.py` content equal after sync: `True`
- C app contains `home_tab` (`首页`): `True`
- C app contains `candidate_page` (`候选商机`): `True`
- C app contains `campaign_page` (`正式商机`): `True`
- C app contains `source_status` (`数据源运行状态`): `True`
- C app contains `today_new` (`今日新增商机`): `True`
- C app contains `source_link_column_config` (`source_link_column_config`): `True`
- C app contains `LinkColumn` (`LinkColumn`): `True`

## 7. Configuration Differences
- None
- `PLATFORM_SOURCE_LIST.yaml` exists in C: `True`

## 8. Requirements / Dependency Differences
- `requirements.txt` equal: `True`

## New Architecture File Confirmation
- `PLATFORM_SOURCE_LIST.yaml`: D=`True`, C=`True`
- `CURRENT_PROJECT_AUDIT.md`: D=`True`, C=`True`
- `DATA_SOURCE_ARCHITECTURE.md`: D=`True`, C=`True`
- `CAMPAIGN_DISCOVERY_DESIGN.md`: D=`True`, C=`True`
- `IMPLEMENTATION_REPORT.md`: D=`True`, C=`True`
- `TEST_REPORT.md`: D=`True`, C=`True`
- `src/game_promo_radar/campaigns.py`: D=`True`, C=`True`
- `src/game_promo_radar/sources.py`: D=`True`, C=`True`
- `src/game_promo_radar/discovery.py`: D=`True`, C=`True`
- `tests/test_campaign_system.py`: D=`True`, C=`True`
- `tests/test_discovery_runtime.py`: D=`True`, C=`True`

## Test Collection Comparison
- D collected tests: `78`
- C collected tests: `78`
- D run result: `78 passed`
- C run result: `78 passed`
- Tests present in D but missing in C after sync:
  - None
- Tests present in C but missing in D after sync:
  - None

## Why 61 Became 78
Before final sync, C lacked `tests/test_campaign_system.py` and `tests/test_discovery_runtime.py`, plus implementation files `campaigns.py`, `sources.py`, and `discovery.py`. Those two test files add 17 collected tests, so C moved from 61 to 78 after syncing the full campaign discovery architecture.

## Remaining Intentional Differences
C contains `.devcontainer/` because it is the Git/deployment repository. Runtime data remains intentionally ignored. After this report is written, C also contains sync report files generated for this audit.

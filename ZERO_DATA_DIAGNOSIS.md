# 零候选数据诊断

诊断时间：2026-07-11

## 已核验事实

执行数据库查询前，先停止了占用 DuckDB 的 Streamlit 进程。查询结果：

- `data_sources`: 22
- `campaign_candidates`: 0
- `campaigns`: 0
- `tasks`: 27
- `crawl_runs`: 8

`data/auto_collect_config.json` 内容：

```json
{
  "enabled": false,
  "daily_time": "09:00",
  "use_current_seeds": true,
  "use_all_history_seeds": false,
  "use_similar_discovery": true,
  "use_keyword_search": false,
  "active_only": true
}
```

`run_once_collect.py` 原状态：只调用 `run_auto_collect()`，而 `run_auto_collect()` 主要写旧 `tasks` 表。候选表是在上一阶段新增的，历史采集发生在候选表和 discovery runtime 之前。

历史 `crawl_runs` 事实：

- `stage9_seed_and_similar_collect`: 成功 13、旧任务新增 10、更新 3。
- `online_public`: 成功 2、旧任务新增 2。
- `stage10_active_seed_collect`: blocked，成功 0、更新 2。
- 没有任何 `discovery_*` 运行记录。

## campaign_candidates 为 0 的真实原因

1. 自动采集未启用：`enabled=false`，Streamlit 启动不会自动产生候选。
2. 旧历史采集发生在 `campaign_candidates` 表和候选 upsert 逻辑加入之前，只写入了旧 `tasks`。
3. `run_once_collect.py` 原来没有显式执行新 discovery runtime，因此命令行一次性采集不保证写候选。
4. 旧 `online_collect` 的详情页阈值较严格，入口页和字段不足页面会被过滤；上一阶段虽已在部分路径加候选同步，但没有重新执行采集，数据库自然仍为 0。
5. 搜索发现原逻辑先按 `is_relevant_result` 过滤，很多搜索结果没有机会保存为原始线索或待验证候选。

## 已修复

- 新增 `python -m game_promo_radar.discovery ...` 独立发现命令。
- 搜索和公开来源发现先写 `discovery_records`。
- 候选保存改为宽松机制：满足任意两个活动信号就保存候选，字段不足标记为 `待验证`。
- `run_once_collect.py` 已追加执行 `run_discovery_all()`。
- 实际执行 `python -m game_promo_radar.discovery all` 后，`campaign_candidates` 从 0 增加到 9。

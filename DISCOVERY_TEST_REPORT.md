# Discovery 测试报告

测试时间：2026-07-11

## 命令

```bat
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m compileall -q app.py src tests health_check.py run_once_collect.py
```

## 结果

- Pytest：78 passed。
- Compileall：通过。

## 新增测试

- `test_search_discovery_saves_incomplete_candidate`
- `test_search_discovery_records_filter_reasons`
- `test_public_source_discovery_extracts_links_and_saves_candidate`
- `test_unknown_domains_become_source_discovery_candidates`

## 实际运行验证

命令：

```bat
set PYTHONPATH=src
.venv\Scripts\python.exe -m game_promo_radar.discovery all
```

结果：

- 扫描来源数：29
- 搜索结果数：24
- 新增候选数：9
- 更新候选数：0
- 正式商机数：0
- 失败来源列表：1 条，HTTP 403，已记录。

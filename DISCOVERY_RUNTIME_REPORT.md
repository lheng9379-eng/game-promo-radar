# Discovery Runtime Report

运行命令：

```bat
set PYTHONPATH=src
.venv\Scripts\python.exe -m game_promo_radar.discovery all
```

运行时间：2026-07-11

## 本次实际输出

- 扫描来源数：29
- 请求成功数：62
- 请求失败数：1
- 发现链接数：34
- 搜索结果数：24
- 新增候选数：9
- 更新候选数：0
- 风险候选数：0
- 被过滤数：25
- 正式商机数：0

过滤原因：

- `no_activity_links_on_list`: 4
- `not_activity_page`: 24
- `only_one_activity_signal`: 1

失败来源：

- `haoyou_kuaibao:https://bbs.3839.com/thread-8929680.htm: HTTP Error 403: Forbidden`

## 数据库结果

运行后查询：

- `data_sources`: 22
- `discovery_records`: 16
- `campaign_candidates`: 9
- `campaigns`: 0
- `source_discovery_candidates`: 0
- `crawl_runs`: 11

`discovery_records` 数量小于发现链接数，是因为该表按 `source_url` 去重更新，重复搜索结果不会重复插入。

## 结论

- 采集流程已真实执行。
- 发现结果能进入候选表。
- 字段不完整页面被保存为 `待验证`，没有被全部丢弃。
- 当前没有正式商机，因为候选尚未人工复核并转入 `campaigns`。
- 数据源配置现在不等同于采集能力，只有 discovery runtime 实际访问并记录成功/失败才算运行。

# 实施报告

## 已完成

- 新增分层数据源配置：`PLATFORM_SOURCE_LIST.yaml`。
- 新增 `sources.py`：加载、校验、同步数据源配置。
- 新增 `campaigns.py`：关键词组合、候选 ID、来源可信度、风险检测、候选校验、收益解析、正式商机评分。
- 扩展 DuckDB schema：
  - `data_sources`
  - `campaign_candidates`
  - `campaigns`
  - `campaign_progress`
  - `crawl_runs.retry_after`
  - `crawl_runs.login_state`
- 公开采集结果同步写入 `campaign_candidates`，正式商机需要人工校验晋级。
- Streamlit 新增：
  - 首页商机发现决策概览。
  - 数据源运行状态。
  - 候选商机页。
  - 正式商机页。
  - 候选校验与转正式商机按钮。
- 手动保存和 Excel 导入同步生成候选商机。
- 当前数据库已迁移，并同步 22 个数据源。

## 未做成伪采集器的部分

- 星图、蒲公英、花火、微博微任务、知乎、视频号等登录平台只预留为 `logged_in_browser` 或手动采集，不编写绕过登录或反爬的适配器。
- 后续适配器应从“用户可见页面读取 + 候选表落库”开始，而不是直接写正式商机。

## 运行结果

- `data_sources`：22 条。
- `campaign_candidates`：当前为 0 条，后续采集或手动导入会先进入候选表。
- `campaigns`：当前为 0 条，候选通过验证后进入。
- 旧 `tasks`：27 条，继续作为兼容情报库保留。

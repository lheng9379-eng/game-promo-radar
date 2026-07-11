# 数据源架构

## 分层

1. 官方任务平台：星图、游戏发行人、磁力聚星、蒲公英、花火、微博微任务等。
2. 品牌和游戏厂商官网：游戏官网、品牌活动页。
3. 官方账号和官方社区：TapTap、B站活动页、游戏官方公开账号。
4. 搜索引擎发现：关键词组合搜索，只作为候选线索。
5. 用户手动添加：链接、Excel、人工补字段。
6. 登录后浏览器采集：Playwright 持久化登录状态，只读取用户正常可见页面。
7. 候选来源自动发现：从已保存页面的链接图谱发现相似活动页。

## 配置文件

主配置为 `PLATFORM_SOURCE_LIST.yaml`。每个来源包含：

- `source_id`
- `source_name`
- `source_type`
- `content_platform`
- `base_url`
- `discovery_method`
- `login_required`
- `parser_name`
- `crawl_frequency`
- `enabled`
- `reliability_level`
- `last_success_at`
- `last_error`
- `consecutive_failures`

## 数据库表

- `data_sources`：来源清单与运行状态。
- `crawl_runs`：采集日志，新增 `retry_after` 与 `login_state`。
- `campaign_candidates`：所有发现结果先进入候选表。
- `campaigns`：验证通过后的正式商机。
- `campaign_progress`：报名、发布、数据观察、结算和实际收益闭环。

## 合规边界

- 公开可访问页面使用普通 HTTP 抓取。
- 需要登录的平台使用用户手动登录后的 Playwright 持久化 profile。
- 不绕过登录、验证码、签名、反爬或访问控制。
- D、E 级来源只作为线索，不能直接作为推荐任务。

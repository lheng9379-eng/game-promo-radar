# 真实公开来源实施报告

## 已实现公开来源发现能力

新增模块：

- `src/game_promo_radar/discovery.py`

实现能力：

- 列表页访问。
- 最近链接提取。
- 详情页抓取。
- 活动关键词识别。
- 候选表落库。
- 快照保存到 `data/snapshots/discovery/`。
- 失败日志写入 `crawl_runs`。
- 过滤原因计数。

## 本次实际参与扫描的公开来源

从 `PLATFORM_SOURCE_LIST.yaml` 选择无需登录且启用的公开来源：

- `bilibili_creator_activity`
- `taptap_creator`
- `haoyou_kuaibao`
- `kuaishou_creator_activity`
- `xiaohongshu_creator_activity`

本次运行证明：

- 列表页成功保存快照：B站、好游快爆、快手等来源已有 `*_list` 快照。
- 好游快爆详情页成功抓取并保存多个 `*_detail` 快照。
- 公开来源发现新增 9 条候选。
- 一个好游快爆论坛详情页返回 403，已记录失败日志。
- 其他列表页当前未发现满足活动链接条件的详情页，记录为 `no_activity_links_on_list`。

## 未实现为伪适配器的平台

以下平台需要登录或存在明显访问控制，仅保留为配置和手动 Playwright 读取入口，未编写自动绕过逻辑：

- 抖音巨量星图
- 小红书蒲公英
- B站花火
- 微博微任务
- 知乎芝士平台
- 微信视频号创作者任务

## 单元测试

新增 `tests/test_discovery_runtime.py`，覆盖：

- 搜索结果字段不完整仍保存候选。
- 非活动页记录过滤原因。
- 公开来源列表页提取详情链接并保存候选。
- 未知域名累计活动后进入潜在新数据源表。

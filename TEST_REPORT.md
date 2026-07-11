# 测试报告

测试时间：2026-07-11

## 命令

```bat
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m compileall -q app.py src tests health_check.py run_once_collect.py
```

## 结果

- Pytest：74 passed。
- Compileall：通过，无错误输出。

## 新增覆盖

- 数据源配置测试。
- 候选任务去重测试。
- 活动有效期判断测试。
- 官方来源可信度测试。
- 风险词识别测试。
- 奖池和实际收益区分测试。
- 相同活动多来源合并测试。
- 登录失效处理测试。
- 采集失败重试测试。
- 来源链接跳转测试。
- 导出测试。
- 关键词组合测试。
- 旧任务表与新候选表分层测试。

# Windows 定时运行指南

本项目现在不需要依赖 Streamlit 页面保持打开即可执行发现任务。

## 可用脚本

- `run_search_discovery.bat`
- `run_public_sources.bat`
- `run_all_discovery.bat`

脚本行为：

- 自动进入项目目录。
- 使用 `.venv\Scripts\python.exe`。
- 设置 `PYTHONPATH=%CD%\src`。
- 日志写入 `logs/discovery/`。

## 手动测试

```bat
cd /d D:\CodexProjects\game-promo-radar
run_all_discovery.bat
```

检查日志：

```bat
type logs\discovery\all_discovery.log
```

## Windows 任务计划程序

1. 打开“任务计划程序”。
2. 选择“创建基本任务”。
3. 名称填写：`Game Promo Radar Discovery`。
4. 触发器选择：每天。
5. 时间建议：每天 09:00 或 10:00。
6. 操作选择：启动程序。
7. 程序或脚本填写：

```text
D:\CodexProjects\game-promo-radar\run_all_discovery.bat
```

8. 起始于填写：

```text
D:\CodexProjects\game-promo-radar
```

9. 保存后，右键任务选择“运行”做一次验证。

## 建议

- 日常使用 `run_all_discovery.bat`。
- 如果只想减少请求量，使用 `run_public_sources.bat`。
- 如果公开来源没有新活动，再手动运行 `run_search_discovery.bat`。
- 登录平台仍需用户手动登录，不通过计划任务绕过登录、验证码或访问限制。

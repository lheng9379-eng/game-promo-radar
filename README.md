# 内容推广商机雷达

主项目目录：

```text
D:\CodexProjects\game-promo-radar
```

个人本地使用的公开内容推广情报整理工具。系统用于回答：

- 这个推广任务是否值得做？
- 适合什么账号做？
- 制作难度是多少？
- 预估价值和结算风险如何？

## 范围

本项目只做公开情报收集、可做性分析、账号匹配、制作难度判断、结算风险判断、截止提醒和 Excel 导入导出。官方平台负责报名和接单。

覆盖范围从游戏推广扩展为内容推广商机，包括游戏、App、电商种草、本地生活、影视短剧、品牌活动、平台激励和其他通过发布作品可能获得奖励、返佣、结算或流量扶持的任务。游戏推广仍作为重点分类保留。

不开发用户注册、多用户权限、任务发布、自动报名、自动接单、自有账号数据采集、私信、团队协作、在线支付或自动结算。任务结果只作为人工备注保存。

## 合规与本地化

- 所有数据只保存在本机 DuckDB 和本地文件夹。
- 不上传云端。
- 不绕过验证码、签名、访问限制和平台反爬。
- 不采集或推荐违规、侵权、刷量、虚假互动、诈骗、灰产相关任务。
- 浏览器登录资料只保存在 `data/browser-profile`，该目录已加入 `.gitignore`。
- 未获取到的数据保存为数据库 `NULL`，页面显示“待确认”，禁止猜测。

## 本地启动

推荐双击项目根目录的：

```bat
start.bat
```

`start.bat` 会自动进入项目目录，优先使用：

```text
.venv\Scripts\python.exe
```

然后启动 Streamlit，并打开：

```text
http://localhost:8503/
```

命令行等价启动方式：

```bat
cd /d D:\CodexProjects\game-promo-radar
.venv\Scripts\python.exe -m streamlit run app.py --server.port 8503 --server.headless true --browser.gatherUsageStats false
```

`run.bat` 保留为兼容旧入口，行为与 `start.bat` 一致：同样优先使用 `.venv\Scripts\python.exe`，端口固定 `8503`，并使用相同的 Streamlit 参数。

停止本项目 Streamlit：

```bat
stop.bat
```

## 自动采集

自动采集是本地功能，不上传云端。配置文件保存在：

```text
data/auto_collect_config.json
```

页面路径：

```text
网上采集 -> 每日自动采集
```

注意：当前阶段自动采集只在 Streamlit 项目运行期间生效。如果电脑关机、终端关闭或 Streamlit 未运行，不会后台自动采集。Windows 计划任务可后续接入。

不打开页面也可以执行一次采集：

```bat
call .venv\Scripts\activate.bat
python run_once_collect.py
```

## 数据

核心数据库统一为：

```text
D:\CodexProjects\game-promo-radar\data\game_promo_radar.duckdb
```

备份目录：

```text
D:\CodexProjects\game-promo-radar\data\backups
```

## 健康检查

运行：

```bat
cd /d D:\CodexProjects\game-promo-radar
.venv\Scripts\python.exe health_check.py
```

会检查：

- 数据库是否存在
- 自动采集配置是否存在
- 最近一次自动采集时间
- Streamlit 端口 `8503` 是否可访问

如果提示“Streamlit 端口 8503 当前未启动，请运行 start.bat”，说明当前没有运行中的页面服务，不一定是错误。需要访问页面时再运行 `start.bat`。

## 测试与验收

```bat
cd /d D:\CodexProjects\game-promo-radar
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m compileall -q app.py src tests health_check.py run_once_collect.py
```

验收通过条件：

- `pytest` 为 `0 failed`
- 编译检查无错误输出
- `start.bat` 启动后 `http://localhost:8503/` 返回 `200`
- `health_check.py` 能识别数据库、配置和当前端口状态

## 版本追踪

当前目录可以不强制初始化 Git。如需后续追踪版本、回滚改动或提交交付记录，可在项目根目录执行：

```bat
git init
```

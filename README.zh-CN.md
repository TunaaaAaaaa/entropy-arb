# 策略研究工作台
[English](README.md)
这里用于搜集证据、提出假设、运行实验和保存结果。不同策略在 strategies/ 下平级组织；Entropy Arbitrage 已归为学习 demo，退出日常使用主路径。
## 项目入口

| 目录 | 用途 |
|---|---|
| [research-workbench/](research-workbench/README.zh-CN.md) | 共用资料、案例、假设、证据与研究数据库 |
| [strategies/](strategies/README.md) | 独立策略的代码、依赖与实验 |
| [Entropy Arbitrage](strategies/entropy-arbitrage/README.zh-CN.md) | 保留用于阅读与测试的原套利 demo |
| [币圈新闻机器人](strategies/crypto-news-bot/README.md) | V0.2：RSS → 关键词分级 → 飞书 / 企业微信长连接 → SQLite |
| [架构与技术债](ARCHITECTURE.zh-CN.md) | 目录边界、兼容安排与后续工作 |

## 本地使用
需要 Node.js 22+、Python 3.11+。根目录没有运行时 npm 依赖，研究工作台单独安装：
```powershell
npm --prefix research-workbench ci
python -m pip install -r research-workbench/requirements-db.txt
```
已配置的本机数据库：启动 Docker Desktop 后，可以直接在仓库根目录运行：
```powershell
npm run db:up
npm run db -- status
npm run workbench -- collect
npm run workbench -- inbox
npm run workbench -- report
npm run db -- records --kind case
npm run db -- export-record case:009
```
原来在 research-workbench/ 内执行的命令继续有效。根目录命令会切换到工作台执行，save-record 等命令的相对文件路径仍以 research-workbench/ 为基准。
报告位置：research-workbench/reports/latest.md。collect 只采集配置中到期的来源；指定文章用 npm run crawl -- URL；全网搜集和 AI 筛选按[本地按需流程](research-workbench/LOCAL-COLLECTION.zh-CN.md)执行。
新克隆不包含数据库、密钥和历史数据。先按[数据库配置与迁移](research-workbench/POSTGRES-MIGRATION-PLAN.zh-CN.md)配置；db:up 不会自动导入历史资料或选择数据库后端。
## 学习顺序
第一周阅读并分析案例；第二周从任意策略方向选一个可验证假设；第三周完成可重复实验；第四周整理反证和结果。天气、社交媒体、套利均可作为独立方向。详见[工作台指南](research-workbench/README.zh-CN.md)与[案例目录](research-workbench/cases/INDEX.md)。
## 新闻机器人 V0.2
在仓库根目录运行。机器人使用自己的 Python 虚拟环境和 SQLite，不需要研究数据库或 Docker：
```powershell
npm run news:setup
Copy-Item strategies/crypto-news-bot/config.example.yaml strategies/crypto-news-bot/config.yaml
npm run news:smoke
npm run news:once -- --dry-run
```
配置子项目 config.yaml 的飞书 Webhook 后，先运行 npm run news:verify 准备并核对一条新闻，再用 npm run news:verify -- --send 单条联调、入库并检查去重。npm run news:once 运行整轮并发送；npm run news:start 按配置定时运行。没有任何可用通知渠道时只预览，不写入已推送表。首次运行会处理 RSS 当前提供的全部条目；它不负责历史文章回溯。详见[操作指南](strategies/crypto-news-bot/README.md)。
企业微信支持 Bot ID / Secret 长连接：npm run news:wecom 检查认证，npm run news:wecom -- --discover 获取目标群 chat_id，npm run news:wecom -- --send-test 发送一条测试消息。凭据和群标识填入本地 config.yaml，参见[企业微信指南](strategies/crypto-news-bot/WECOM.md)。启用后两个渠道分别记录投递结果；没有任何可用渠道时才只预览。
## 验证
```powershell
npm run test:workbench
npm run test:db
npm run test:demo
npm run test:news
```
数据库测试需要已配置 PostgreSQL，并在隔离测试库运行。demo 测试需要单独安装其 Python 基础依赖与 pytest；测试不会启动交易。
## 数据与兼容
研究数据库、research-workbench/data/ 和现有 Compose 名称/卷保持原位。根目录 logs/ 保留为历史数据入口；新的策略输出使用各自目录。原根目录 .env 和 config.yaml 已在本机移动到 demo 目录，仍被 Git 忽略。
数据库备份：npm run db -- backup-pg。数据库与其引用的证据文件需要一起备份；Git 推送不包含采集原文、私人配置或数据库。

## 项目职责
仓库根目录负责导航与 npm 命令转发；research-workbench 负责资料、证据和研究记录；strategies/<strategy-id> 负责可独立开发的策略或监控实现。本机根目录已改为 strategy-lab，子项目各自解析相对路径。
## 新闻机器人 V0.2
strategies/crypto-news-bot 与 entropy-arbitrage 平级，实现 RSS → NewsItem → 去重/分级 → 飞书 Webhook / 企业微信长连接 → SQLite。Python 实现加 npm 启动入口；使用独立虚拟环境和 data/news.db，保持研究工作台 PostgreSQL 的职责边界。
experiments/001-rss-feishu-smoke 记录验收定义；smoke_test.py 使用模拟 RSS、模拟通知器和临时 SQLite，并可将带输入哈希、代码版本与运行计数的记录写入 data/runs/。模拟验收不记为真实新闻或策略收益。
本版的定时执行由用户启动的本地进程负责；未部署 Docker 或后台服务。企业微信由一个接收线程维持长连接，处理认证、心跳、重连和回执；凭据与目标群写在本地 config.yaml。news_deliveries 按目标保存成功状态，避免局部失败导致重复发送成功渠道；pushed_news 保留汇总与兼容用途，升级时迁移旧飞书历史。推送历史目前不自动同步到研究数据库；跨进程去重与发送/入库之间的崩溃恢复仍待后续处理。
## 本轮整理
Entropy Arbitrage 的源码、测试、分析工具、配置示例、依赖与原教程移动到 strategies/entropy-arbitrage。双语根 README 改为研究入口，历史交易说明归到 demo。LICENSE 与 Git 历史保留。
本机 .env/config.yaml 随 demo 移动，未读取或提交其内容。旧根 logs/ 保留，避免改变既有数据库引用；行情导入与 SQLite 备份同时识别旧 logs/ 和新 strategies/*/logs/。
研究工作台、数据库名称、Compose 项目名、端口与数据卷未迁移。PostgreSQL 备份原本按登记证据查找文件，不需要改数据位置。
根 npm 命令转发到各子项目；研究命令不安装或加载交易签名 SDK。demo 只提供测试、帮助、分析和只读采集的 JS 入口；历史 Python 主程序仍保留原始行为。
records 可浏览全部案例，export-record 可用唯一前缀；用户输入错误输出简短提示。案例索引补齐 005。学习路线以工作台四周研究闭环为主，十二周技术路线作为按需参考。
备份/恢复回归测试发现 SQLite 连接上下文只提交事务、没有关闭文件，已增加显式关闭以避免 Windows 文件锁；demo 内容渲染测试使用固定视口，避免终端宽度影响断言。
## 数据兼容
不可变证据副本、文档版本、案例版本及数据库内已保存的历史路径不批量改写。历史文章里引用旧 main.py 路径属于旧记录；当前操作文档采用新路径。Git 只保存源码与可编辑研究材料，data/、reports/、logs/、密钥与数据库备份仍需本地备份。
## 后续技术债

| 项目 | 现状 | 合适的处理时机 |
|---|---|---|
| 策略/实验/运行注册 | 数据库有案例、假设和旧实验结果，无完整策略层 | 第一个新策略接入时设计迁移与通用结果导入 |
| 旧实验导入格式 | 固定 events.json、replay.py、result.json；历史代码归属有限 | 实施通用导入时保留兼容入口并增加真实运行清单 |
| 文件到数据库同步 | Markdown 修改需显式 save-record | 提供编辑工作流时增加未保存提示，不能静默改历史版本 |
| Demo 依赖 | 原有 Python 依赖为范围约束，实盘 SDK 含非固定 Git 版本 | 仅在确实需要复现实盘环境时锁定；当前不安装或升级 |
| 采集覆盖与备份 | X 全量搜索、调度、异地备份尚未配置 | 用户需要持续运行或远程部署时处理 |

本轮没有建设调度平台、启动策略常驻服务或改数据库 schema。新策略可先独立验证实验，再决定是否容器化。

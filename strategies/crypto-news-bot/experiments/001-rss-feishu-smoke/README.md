## EXP-001：新闻机器人最小闭环
strategy_id：crypto-news-bot；experiment_id：001-rss-feishu-smoke；模式：synthetic。
初次执行结果见 [2026-09-11 验收记录](VALIDATION.md)。
目标：验证一条固定 P0 新闻能经过统一模型、RSS 解析、分级、消息生成、模拟投递和 SQLite 持久化；重复运行不重复发送。本实验验证工程流程，不评价新闻价值、预测准确率或交易收益。
## 输入与验收标准
固定输入：tests/fixtures/news.xml。新闻标题为 Binance announces listing of TEST token，链接为 https://example.com/test-news，来源 MockSource。
使用 config.example.yaml 的关键词。首轮 fetched=1、pushed=1、数据库行数=1；重新打开数据库后第二轮 duplicates=1、pushed=0，MockNotifier 总共只收到 1 条消息。
## 运行
在仓库根目录运行：
```powershell
npm run news:smoke -- --report data/runs/smoke-latest.json
npm run test:news
```
报告位于子项目 data/runs/smoke-latest.json，记录代码 HEAD、工作区是否有未提交改动、输入与配置哈希、Python 版本、运行时间、计数与结论。报告不含 Webhook；使用临时数据库，结束后清理，不污染真实推送记录。未提交源码无法只凭 HEAD 重现，复核时应同时保存对应工作区代码。
## 后续实测
先运行 npm run news:once -- --dry-run，确认来源抓取计数和候选消息。填写目标群 Webhook 后运行 npm run news:verify，保存并核对一条新闻；npm run news:verify -- --send 只发送该条并检查 pushed_news，第二轮自动使用同一条新闻验证跳过重复。结果写入 data/runs/feishu-verification.json；另需在目标群核对消息。
真实 RSS 可达性、实际群消息、断网后重试要分别记录，不能用离线 SMOKE TEST PASSED 代替。先独立保存实验记录，通用研究数据库导入后续再接入。

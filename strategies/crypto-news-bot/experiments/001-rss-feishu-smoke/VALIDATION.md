## V0.1 验收记录：2026-09-11
环境：Windows、Python 3.13.5、Node.js 24.15.0。通过根目录 npm run news:setup 创建子项目独立 .venv，并生成未填写 Webhook 的本地 config.yaml。
## 离线验收
执行 npm run news:smoke -- --report data/runs/smoke-latest.json，输出 SMOKE TEST PASSED。
首轮固定假新闻 fetched=1、pushed=1、failed=0；重新打开临时 SQLite 后第二轮 duplicates=1、pushed=0；模拟通知器总计接收 1 条消息。
执行 npm run test:news，45 项测试通过。包含本机回环 HTTP RSS → 实际 requests 请求与 feedparser 解析 → 模拟飞书 HTTP 端点 → SQLite → 再次运行去重，以及失败重试、缺少 Webhook、业务错误码、全部来源失败和调度回调。
## 真实 RSS 预览
执行 npm run news:once -- --dry-run，时间为 2026-09-11 22:22（Asia/Shanghai）：

| 来源 | 本次结果 |
|---|---|
| CoinTelegraph | 解析 30 条 |
| CoinDesk | 解析 25 条 |
| Decrypt | ReadTimeout，本轮跳过 |

总计 fetched=55、source_errors=1、low_priority=47、candidates=8、previewed=8、pushed=0、failed=0。程序正常退出；没有向真实群发送消息，预览条目没有写入已推送表。来源结果是本次运行观察，不保证下次运行仍相同。
本机详细输出：子项目 data/runs/live-rss-preview.log；离线 JSON 记录：data/runs/smoke-latest.json。这些运行文件不进入 Git。
## 尚待实测
未配置目标群飞书 Webhook，所以实际群投递尚未验证。填写后运行 npm run news:once，核对群消息、SQLite 推送记录和第二次运行的重复计数。
本次没有部署常驻后台进程，没有验证所有 RSS 源持续可用。Decrypt 本轮超时已验证失败隔离，未将它记为成功抓取。
## 2026-09-12：真实联调准备
本机已配置飞书自定义群机器人 Webhook，初始 pushed_news 为 0 条。没有在本记录中保存地址或密钥。
增加 npm run news:verify：默认只准备一条未推送新闻；带 --send 时发送保存内容，再检查入库和重复跳过。配置目标变化或快照内容不匹配会停止发送。新增测试后 npm run test:news 共 56 项通过，覆盖单条发送、持久化去重、失败不重试、目标变更与空结果使旧快照失效等情况。此处测试的通知器均为模拟。
10:56（Asia/Shanghai）真实 RSS 预览：CoinTelegraph 30 条、CoinDesk 25 条、Decrypt 55 条；共 110 条，30 条候选、1 条 IGNORE、79 条 P2、0 来源错误，未发送。
11:01 联调准备：CoinTelegraph 30 条、CoinDesk 25 条、Decrypt 35 条；共 90 条，14 条未推送候选、0 来源错误。两轮 RSS 条目数变化是实际观测，结果按各自轮次记录。
准备发送的新闻为 CoinTelegraph 的 Bitcoin ETF outflows accelerate as investors pull $449M in three days，P0；完整消息保存于 data/runs/feishu-pending.json。此时只完成准备，尚未执行 --send，不能记为飞书真实投递通过。
## 2026-09-12：飞书真实验收完成
在用户明确要求测试发送后，于 11:09（Asia/Shanghai）执行 npm run news:verify -- --send。飞书接口确认成功，首轮 pushed=1、failed=0，SQLite 从 0 增加到 1 条；第二轮 duplicates=1、pushed=0，没有再次发送。真实联调结果 passed，回执保存在 data/runs/feishu-verification.json。
之后接入企业微信长连接及按目标投递记录。本机配置和旧数据库先备份到 data/local/，其中含私人配置的备份不进入 Git。企业微信目前尚缺 Bot ID、Secret，实际群连接待配置后验收；本机协议与兼容测试见 [EXP-002](../002-wecom-long-connection/README.md)。
11:31 升级后再次用同一快照验收，结果 already_pushed，两轮均 duplicates=1、pushed=0，没有重复发出消息。数据库保留 1 条 pushed_news 和 1 条按目标的 news_deliveries 记录；结果见本机 data/runs/feishu-after-channel-migration.json。V0.2 smoke test 和全部 75 项测试通过。

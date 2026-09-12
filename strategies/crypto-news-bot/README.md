# 币圈新闻监控与推送机器人 V0.2
这是 strategy-lab 下的独立实验子项目，与 entropy-arbitrage 平级。流程为 RSS → NewsItem → 去重 → 关键词分级 → 消息格式化 → 飞书 Webhook / 企业微信长连接 → SQLite。
## 安装与配置
需要 Python 3.10+；从仓库根目录使用 npm 入口时还需要 Node.js。以下 PowerShell 命令在仓库根目录执行，setup 为本子项目创建 .venv，不修改其他项目的 Python 依赖：
```powershell
npm run news:setup
Copy-Item strategies/crypto-news-bot/config.example.yaml strategies/crypto-news-bot/config.yaml
npm run news:smoke
```
已有 config.yaml 时跳过复制，避免覆盖 Webhook 和关键词。配置与 data/ 被 Git 忽略；数据库路径相对于配置文件所在目录解析。
也可以在子项目目录直接使用 Python：
```powershell
cd strategies/crypto-news-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.yaml config.yaml
python smoke_test.py
python main.py --once --dry-run
```
macOS/Linux 对应激活命令为 source .venv/bin/activate，复制配置使用 cp config.example.yaml config.yaml。npm 自动优先使用本项目 .venv；NEWS_BOT_PYTHON 可指定替代解释器。
## 配置飞书 Webhook
在目标飞书群添加自定义机器人，取得 Webhook，并填写本子项目 config.yaml：
```yaml
notifiers:
  feishu:
    enabled: true
    webhook_url: "在这里填写目标群机器人的完整 Webhook"
```
这里使用自定义群机器人 Webhook，与工作台其他飞书连接器独立。发送 text JSON；请求超时为 10 秒，并检查响应中的业务成功码。若机器人设置了自定义关键词，消息必须满足该限制；本版没有实现签名校验参数，启用签名校验的机器人需要后续补充签名适配。
Webhook 留空时会明确提示并跳过飞书；仍可通过其他已配置渠道投递。没有可用通知器时才只预览，不写入 pushed_news。不要将真实地址写进示例文件或验收记录。飞书接口说明见[官方自定义机器人指南](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)。
## 企业微信长连接
在本地 config.yaml 的 notifiers.wecom 填写 bot_id、secret、目标企业微信群的 chat_id。缺少群标识时，先保持 enabled: false，再运行以下命令并在目标群 @机器人：
```powershell
npm run news:wecom
npm run news:wecom -- --discover
```
将获取的群标识填入 chat_id 后，用 npm run news:wecom -- --send-test 发送一条测试消息；确认后将 enabled 改为 true，即可与飞书一起接收新闻。完整配置、凭据来源、心跳重连和会话发现见[企业微信接入指南](WECOM.md)。
## 本地运行
首次飞书真实联调可先准备并核对一条新闻。在仓库根目录运行（这些 verify 命令只验证飞书渠道）：
```powershell
# 抓取并保存一条未推送的 P0/P1 新闻；此命令不发送
npm run news:verify
# 发送刚才保存的那一条，检查 SQLite 入库，再以同一条新闻验证去重
npm run news:verify -- --send
```
待发送完整内容保存在 data/runs/feishu-pending.json，发送结果在 data/runs/feishu-verification.json。发送命令使用保存的内容，不重新抓取或换一条新闻；优先选择 P0，再选 P1，同级采用 RSS 返回顺序。待发送内容或筛选规则不再匹配、目标 Webhook 已更换时，需要重新准备。快照只记录目标地址的哈希，不包含 Webhook。
准备阶段没有候选会覆盖旧待发送快照，防止误用上次新闻。投递失败只尝试一次，保留失败记录，退出码为 1；配置或快照错误退出码为 2。成功后重跑同一份快照会返回 already_pushed 并跳过发送。接口确认成功不代表群成员已读。
以下命令在仓库根目录运行：
```powershell
# 真实 RSS 抓取，仅预览，不发送
npm run news:once -- --dry-run
# 运行一轮：配置了 Webhook 就真实发送，随后退出
npm run news:once
# 启动定时监控；示例配置为每 10 分钟一次，Ctrl+C 停止
npm run news:start
# 使用其他配置（相对路径以子项目目录为基准）
npm run news:once -- --config D:/my-config/news.yaml
```
子项目内的等价 Python 命令是 python main.py --once --dry-run、python main.py --once、python main.py。app.run_once: true 会使 python main.py 只运行一轮；--once 优先于配置。首次启动立即抓取一次，然后按 interval_minutes 定时执行。窗口关闭或电脑休眠期间不会持续监控。
单个 RSS 源、单条新闻或通知失败会记录日志，其他条目继续处理；所有源失败时本轮正常结束。日志中的 source_errors / failed 大于 0 表示业务失败，退出码 0 只表示这一轮正常结束，不能当作真实推送成功的证据。配置错误退出码为 2。
## 分级与推送记录
默认读取 CoinTelegraph、CoinDesk、Decrypt 的 RSS，实际可用性取决于来源。判断范围为 title + summary + raw_content，大小写不敏感；RSS 摘要里的 HTML 转为纯文本，raw_content 仅取 RSS 提供的正文，不额外抓取文章网页。

| 优先级 | 规则 | 默认动作 |
|---|---|---|
| P0 | 命中 high_priority_keywords | 推送 |
| P1 | 命中 medium_priority_keywords | 推送 |
| IGNORE | 命中 ignore_keywords，且没有命中更高优先级 | 跳过 |
| P2 | 未命中以上规则 | 跳过 |

优先顺序为 P0 > P1 > IGNORE > P2，因此高优先级覆盖忽略词。英文按完整词/短语匹配，避免 SEC 误命中 second、AMA 误命中 drama；不做词形还原，若需要 hacked、hacking 等形式，请加入关键词配置。中文关键词可以直接匹配。
news_id 优先取链接的 SHA-256；无链接时使用标题和来源生成哈希。data/news.db 的 news_deliveries 表按新闻与发送目标记录各渠道成功状态；本轮全部目标成功后写入 pushed_news 汇总表。某一渠道失败，下轮只重试未成功的目标。失败项本轮不反复尝试，下轮 RSS 仍包含该条目时重试。
从 V0.1 首次打开数据库时，原 pushed_news 记录迁移为历史飞书投递，首次由飞书渠道运行时绑定到当时配置的 Webhook；升级时请保留原 Webhook。新增企业微信不会把旧记录误认为已发给企业微信。更换群目标会建立新的投递身份；WeCom 只更换 Secret 不会重置同一 Bot 和群的去重状态。
第一轮会处理 RSS 当前返回的全部条目，不限定“程序启动以后发布”。本版没有历史回溯、文章存档、失败队列或 URL 跟踪参数归一化；源删除了失败条目后，它不会自行恢复重试。P2、IGNORE、预览消息不会进入已推送表。
支持飞书和企业微信同时投递。请只启动一个使用同一数据库的实例；发送成功与数据库提交之间若进程退出，或服务端已接收但回执丢失，后续重试可能重复发送，本版不保证严格只投递一次。启用新渠道时会处理当前 RSS 中尚未向该目标投递的候选新闻。
## Smoke test 与测试
在仓库根目录：
```powershell
npm run news:smoke
npm run test:news
# 保存可复查的实验记录
npm run news:smoke -- --report data/runs/smoke-latest.json
```
或者在子项目内运行 python smoke_test.py，成功会输出 SMOKE TEST PASSED，失败会给出具体原因并返回非零退出码。它使用固定假新闻、真实 RSS 解析器、生产主流程、MockNotifier 和临时 SQLite，跑两轮确认只发一次；不依赖真实 RSS/Webhook，也不修改正式推送记录。
pytest 额外覆盖 HTTP 200 业务失败、超时、重试、缺失字段、坏源、配置校验及调度回调。使用本机回环 HTTP 服务贯通 requests → feedparser → 飞书 JSON → SQLite；这是本机模拟服务验收，不是实际飞书群验收。
企业微信用本机 WebSocket 服务验证认证、业务回执、心跳、断线重连、群标识发现、退出清理和消息长度；双渠道测试验证局部失败不重复发送成功渠道，以及旧飞书数据库迁移。实验说明见 [002-wecom-long-connection](experiments/002-wecom-long-connection/README.md)。
实验定义见 [001-rss-feishu-smoke](experiments/001-rss-feishu-smoke/README.md)，实际执行情况见 [2026-09-11 验收记录](experiments/001-rss-feishu-smoke/VALIDATION.md)。JSON 验收结果先独立保存，不自动导入研究工作台数据库。
## 支持范围与扩展
V0.2 提供多个 RSS 源、统一 NewsItem、关键词分级、SQLite 按渠道去重、飞书 text 推送、企业微信长连接 markdown 推送、单轮/定时运行与离线验收。暂不包含 X、Telegram、交易所 API、AI 摘要、Web UI、Docker、自动交易、行情或链上监控。
新数据源继承 src/fetchers/base.py 的 BaseFetcher，返回 NewsItem，并在 fetchers/__init__.py 注册；新通知器继承 BaseNotifier，在 notifiers/__init__.py 注册。两者还需在 config.py 增加对应配置校验。main.py 只调用工厂和通用处理流程，无需加入渠道发送逻辑。
Telegram、PushPlus 配置仍是禁用的预留项；设为 enabled: true 会明确报“尚未实现”。企业微信已启用但凭据或目标群缺失时会报配置错误；不会静默漏掉该渠道。
调度采用 APScheduler 3.x，设置 max_instances=1 和 coalesce=True，避免同一进程因上一轮较慢而重叠抓取或补跑多轮，参考[官方调度指南](https://apscheduler.readthedocs.io/en/3.x/userguide.html)。

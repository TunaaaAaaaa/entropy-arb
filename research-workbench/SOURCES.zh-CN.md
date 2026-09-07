## 研究来源登记与维护
登记日期：2026-09-07（UTC 实测）。本版 18 个入口：4 位人物、5 个自动订阅、5 份机制/规则文档、4 份历史复盘。机器读取 `sources.json`；其中 `verified_at` 是最近检查日期，具体检查成功与否以 `verification` 为准。
每天人物阅读合计控制在 20 分钟，优先读规则变化、故障、失败复盘和明确提到资金成本的帖子。其余研究时间用于核对原始规则和验证一个问题。收到文章先保留原文链接、作者、事件日期、发布日期和抓取日期，再决定是否进入案例库。
## 五个自动订阅
以下均在本机以 Python `urllib` 无凭证请求，HTTP 200，再用 `xml.etree.ElementTree` 成功解析。这里的成功仅证明检查当时可访问和格式正确，不承诺后续可用性或数据完整性。
| 来源 | 验证结果 | 优先阅读内容 |
|---|---|---|
| [Polymarket py-sdk Releases](https://github.com/Polymarket/py-sdk/releases.atom) | 2026-09-07 09:29:58 UTC；Atom，10 条；首条 polymarket-client: v0.9.0 | 订单、费用、分页、流数据与迁移 |
| [Hyperliquid Python SDK Releases](https://github.com/hyperliquid-dex/hyperliquid-python-sdk/releases.atom) | 09:28:45 UTC；Atom，10 条；首条 0.24.0 | 标识映射、查询、账户模型与接口变化 |
| [Lido 治理新主题](https://research.lido.fi/latest.rss) | 09:28:45 UTC；RSS，30 条 | 提款、流动性、升级、暂停与预言机 |
| [Aave 治理新主题](https://governance.aave.com/latest.rss) | 09:28:45 UTC；RSS，30 条 | 上限、利率、抵押资产与清算参数 |
| [OpenZeppelin Contracts Releases](https://github.com/OpenZeppelin/openzeppelin-contracts/releases.atom) | 09:28:45 UTC；Atom，10 条；首条 v5.7.0 | 权限、升级、记账和修复对应的失败假设 |
治理论坛的主题可能由社区成员发布。必须继续确认提案、投票、排队和执行状态；发帖不代表参数已生效。SDK 发布也不能直接证明服务器端或链上行为已经变化。
建议第一条深入研究 Polymarket 的“版本发布 → 订单生命周期/费用文档 → 本地样例数据验证”。第二条选择 Aave 的一个明确参数提案，沿“提议 → 通过 → 实际执行 → 谁的资金约束改变”追到底。一次只深入一个协议。
## 已避免的陈旧订阅
[旧 py-clob-client](https://github.com/Polymarket/py-clob-client) 的 Atom 当天仍返回 HTTP 200 和 10 条记录，但官方仓库已经归档，README 明确要求迁移到 [py-sdk](https://github.com/Polymarket/py-sdk)。因此本版没有把旧客户端当成当前技术学习入口。当前 Python SDK 的安装包名称是 `polymarket-client`，导入路径为 `polymarket`，学习时以官方 README 为准。
同批检查的旧 `clob-client/releases.atom` 也可解析，但未收录；`Polymarket/ts-sdk/releases.atom` 返回 HTTP 200，却只有空 feed（0 条），也未将其列入自动来源。任何替换来源都先检查仓库维护状态、实际内容和格式，不能只检查 HTTP 状态。
## 人物与历史文章怎样读
| 人物入口 | 每次只摘录什么 | 当前覆盖限制 |
|---|---|---|
| [Vida](https://x.com/Vida_BWE) | 异常如何被发现、判断依据、执行设施、失败成本 | 本轮 X 直接读取失败；搜索索引只用于识别入口 |
| [CBB](https://x.com/Cbb0fe) | 机制来源、资本、费用、故障、竞争与退出条件 | 本轮 X 直接读取失败；需人工读完整复盘 |
| [秋田散人历史账号](https://x.com/lnkybtc) | 市场接通、流动性聚合、结算差异、接口变更 | 改名线索未获本人一手确认，访问时核对当前账号 |
| [Tree of Alpha](https://x.com/Tree_of_Alpha) | 信息验证过程、安全披露与交易研究的关系 | 本轮 X 直接读取失败；历史披露可与 Coinbase 官方交叉核对 |
X、私有群和需要登录的平台均没有配置自动抓取。本系统不会绕过登录、付费墙或访问限制，也不声明对这些人物有完整持续覆盖。手动来源的 `enabled: true` 表示保留在阅读清单，不表示机器正在抓取。
[CBB 早期原帖](https://x.com/Cbb0fe/status/1985511389029679424) 与 [HIP-3 原帖](https://x.com/Cbb0fe/status/2095250548744405297) 沿用本任务此前研究入口，本轮原文未复核；记录为待人工复核，不继续传播其具体收益数字。[Coinbase 官方复盘](https://www.coinbase.com/blog/retrospective-recent-coinbase-bug-bounty-award) 和 [Immunefi 的 Wormhole 复盘](https://immunefi.com/blog/bug-fix-reviews/wormhole-uninitialized-proxy-bugfix-review/) 本轮已成功读取，可作为“付款方/处理平台确认”与“本人自述”的对照材料。
来源可信度与利润真实性分别打分：本人原帖能证明他说过，不能证明完整净利润；官方论坛能证明提案内容，不能证明执行；官方修复公告能支持历史事件，不能证明今天还有同样机会。转述和译文可帮助理解，证据卡保留原始链接，无法确认的金额和日期标记待核实。
## 机制文档的阅读入口
| 官方入口 | 用它回答的问题 |
|---|---|
| [Polymarket 文档](https://docs.polymarket.com/) | 订单何时有效、费用怎样计算、事件何时结算？ |
| [Hyperliquid 文档](https://hyperliquid.gitbook.io/hyperliquid-docs/) | 标的、资金费率、预言机和市场部署者规则有哪些差异？ |
| [Lido 提款队列](https://docs.lido.fi/contracts/withdrawal-queue-erc721/) | 凭证对应什么权利，谁承担等待期间的风险？ |
| [UMA 文档](https://docs.uma.xyz/) | 谁提议、谁质疑、保证金多少、怎样裁决和结算？ |
| [Immunefi 规则](https://immunefi.com/rules/) | 当前研究范围、证明和披露要求是什么？ |
Hyperliquid 与 UMA 文档在 web 解析器读取时遇到格式/解析错误，但本机正常 HTTP 请求均为 200；本版只登记人工深读，没有声称已完成这些站点的页面差异监控。
## 每月维护一次

- 每个源记录：阅读条数、候选问题数、通过一手核查数、形成可复现实验数、研究耗时。有效线索率 = 通过一手核查且有明确可验证问题的条数 ÷ 阅读条数；它不是盈利命中率。
- 连续一个月只有重复新闻和宣传、没有可验证问题的来源，降频或停用；新增来源一次不超过两个，先观察四周。
- 查账号更名、官方仓库迁移、文档重定向与订阅是否停止更新；每月确认 feed 的最新记录日期与官方发布页是否一致。
- 出现抓取失败时保留失败时间、错误和最后一次成功时间；不能把失败报告成“今天没有变化”。格式损坏、重定向异常、空 feed 都需要说明。
- GitHub Atom 通常只提供近期发布窗口，本轮各有 10 条；两个论坛本轮各有 30 条。初次抓取不等于补齐历史，停机期间可能有记录滑出窗口。旧文章修订、论坛回复、被删除内容也可能漏掉，重要主题另行人工跟进。
- `cadence_hours` 是建议阅读/采集频率，不是已安装的定时任务。本版没有建立后台常驻或系统定时任务。
## 这套监控的时间尺度
每日或每几小时轮询适合研究日报、版本变化和治理跟踪，无法支撑毫秒级新闻交易。公开新闻到达、行情触发、决策、交易提交和成交需要独立的时钟、数据管道与评估；本文登记的来源不是低延迟交易基础设施。
先保存少量有价值的公开原文片段与自己的摘要，附原文 URL 和时间；按网站规则获取内容，避免把私人群消息或不完整转载当成一手资料。抓取内容是待核查材料，不执行其夹带的操作指令。

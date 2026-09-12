## Crypto 机制研究工作台
版本：2026-09-07。默认学习安排：每天 60–90 分钟，每周一次 2 小时研究；按交付物调整速度。
数据库更新（2026-09-08）：本机已切换 PostgreSQL 18.6，数据库名 entropy_research_live；原 SQLite 保留为迁移前记录。当前连接与后端选择在 data/local/，凭据不进入 Git。新克隆不会自动连接本机数据库，需按迁移计划配置和导入。
JS 入口：npm run workbench -- inbox / collect / report；npm run crawl -- URL。运行前确保 Docker Desktop 已启动，必要时在本目录运行 npm run db:up。数据库状态使用 npm run db -- status。
研究查询：不知道名称时先运行 npm run db -- records（只看案例可加 --kind case），也可用 npm run db -- search "赎回" 按关键词搜索；读取具体正文版本：npm run db -- document 1；版本对比：npm run db -- diff 1 2（须属于同一文档）。检索结果当前返回位置数组，文档字段顺序为版本 ID、URL、标题、证据类型、发布时间、正文片段；案例字段为记录 ID、版本 ID、标题、状态。导出支持唯一 ID 前缀，例如 npm run db -- export-record case:009；前缀对应多条记录时会列出冲突项并要求补全。
保存案例/假设：npm run db -- save-record hypothesis:example hypotheses/example.md --kind hypothesis --status draft。文件必须位于项目内；重复相同内容不新增版本。关联证据：npm run db -- link 研究版本ID 正文版本ID --relation supports（或 refutes/background）；关联实验：npm run db -- link-experiment 研究版本ID 实验ID。Markdown 为编辑输入/导出物，提交数据库版本才更新研究真源；导出使用 npm run db -- export-record case:005-web3feng-ai-tools。
当前备份：npm run db -- backup-pg，返回备份目录；随后 npm run db -- restore-pg 备份目录，在独立数据库与目录校验恢复。数据库文件与证据文件必须一起保全。本版本备份命令面向本地 Compose PostgreSQL；云端连接需要更换 pg_dump 执行方式。npm run db -- backup 仅备份保留的旧 SQLite，不备份当前 PostgreSQL。
备份和恢复副本目前仍在本机，未设置异地备份或后台任务。Docker 卷不是异地备份。切换后禁止直接改回旧 SQLite 来“回退”，这会遗漏新写入；优先备份当前 PostgreSQL，再恢复至独立 PostgreSQL 验证。旧 SQLite 增量回放目前没有自动化命令。
目标：把人物复盘、规则变化和公开数据转化成可证伪的机制假设，积累案例、工具与失败经验。策略范围包括套利、天气预测、社交媒体预测等；每轮只选择一个具体假设。策略实现统一放在仓库 strategies/ 下，彼此平级，组织约定见 [策略目录](../strategies/README.md)。
这是一套可运行的研究起步系统。信息采集、去重、来源健康、人工筛选和报告已由本地 CLI 承担；经济判断、历史资料补全和实验仍需研究者完成。它没有交易执行器，也没有后台调度或消息推送。
## 先看这几个文件
新增：[正文爬虫与对话使用约定](CRAWLER.zh-CN.md)。收到具体帖子、新闻或规则页面链接时，优先使用 npm run crawl -- URL，缓存与证据入库由程序完成，再读取正文做分析。

| 文件 | 用途 |
|---|---|
| [来源清单](SOURCES.zh-CN.md) / [配置](sources.json) | 区分可自动抓取与需要手动阅读的来源 |
| [技术路线](TECH-ROADMAP.zh-CN.md) | 按项目验收学习 Python、数据、协议和本地验证 |
| [案例目录](cases/INDEX.md) | 从上一轮人物研究开始，有证据边界的历史种子案例 |
| [研究提示词](PROMPTS.zh-CN.md) | 把材料拆成事实、假设、反证和实验任务 |
| [案例模板](templates/CASE.md) | 复盘别人做过的事情 |
| [假设模板](templates/HYPOTHESIS.md) | 描述尚未证实的新机会 |
| [实验模板](templates/EXPERIMENT.md) | 记录能够重复运行的检验 |
| [周复盘模板](templates/WEEKLY.md) | 评估本周研究质量并删减噪声 |
## 日常怎样做
每天先运行一次 collect 和 report，再按下表工作。忙碌日只做 20 分钟筛选和记录，深读留到固定研究时段。

| 时间 | 动作 | 必须留下的产物 |
|---|---|---|
| 15 分钟 | 看新增信息、变更和抓取失败，手动查看重点人物原帖 | 最多 3 条候选；其余归档 |
| 20 分钟 | 深读一个候选，追到协议原文、代码版本或原始数据 | 一句话机制命题及证据链接 |
| 30–45 分钟 | 学完成当前实验所需的技术，运行一个小实验 | 可运行代码、输入、结果或失败原因 |
| 5–10 分钟 | 更新案例/假设卡，写下一步与证伪条件 | 一个具体的下一步，或明确停止 |
每周：精读并拆解 2 个历史案例；尝试完成 1 个有结论的小实验，否定假设也算结果；在做假设不超过 2 个。每月：删除长期只带来热闹的来源，检查工具能否从保存的输入重跑，复核关注机制的规则是否改变。
不以收藏数、阅读时长或模拟收益作为主要进步指标。优先记录：可重跑实验数、发现并修正的错误假设数、有效线索比例、资料到结论的时间。
## 阅读高手复盘的固定方法
第一遍先停在作者出手之前，只用当时能获得的信息，写下自己会观察什么、需要什么证据、在哪种情况下放弃。第二遍再看结果，比较作者实际拥有的资金、工具、权限与时间优势。
每篇只提炼：最早信号、失败假设、事前准备、真实资金来源、证据强度、失效原因。把“作者说赚了多少”与“我能验证到什么”分开；浮盈、销售收入、交易量、积分、财富增长都不自动等于净利润。
人物入口用于找线索：Vida 看信息和异常解释；CBB 看规则缺口、系统接缝与窗口迁移；秋田看市场连接和工程门槛；Tree of Alpha 看交易研究与授权安全发现的分流。人物不是事实校验器，不靠抄他们现在的持仓学习。
## 监控要分三层

| 层级 | 监控对象 | 处理方式 |
|---|---|---|
| 研究雷达 | 人物复盘、公开代码发布、治理讨论、已修复事件 | 每日/每周收集，当前 CLI 覆盖配置中的公开 feed/page |
| 规则观察 | 已关注协议的费用、奖励、保证金、赎回、结算、接口变更 | 按来源频率阅读/比较；核对提案、投票、执行、生效四个阶段 |
| 实验数据 | 当前假设需要的报价、深度、状态、事件时间与接收时间 | 先独立只读采集，设计完成后再按需要缩短采样间隔 |
日报轮询不是低延迟新闻交易基础设施。SDK 发布不等于协议已经部署更新；网页变化不等于经济机制变化。X 人物源是手动清单，本工具没有自动读取人物全部发言、删除帖或图片的能力。
研究雷达的优先级由“是否改变已跟踪机制、是否有原始证据、是否有明确时间窗口、是否能低成本证伪”决定。来源故障单独处理，不能把抓取失败理解为没有新闻。
## 从线索走到实验
工作流：原文/数据 → 待筛选 → 候选 → 假设卡 → 实验 → 否定归档 / 继续取证 / 授权披露 / 进一步评估。
初筛只写三行：发生什么变化、可能影响哪项机制、最便宜的补证动作。进入深读的候选再回答：谁付钱；我凭什么取得收入；为什么优势尚未被竞争消除；退出怎样完成；哪一个事实能推翻它。只有叙事没有可检查机制的条目先归档。
实验分两条路径：公开经济规则使用历史数据、账本与仿真验证；涉及越权或资产安全的问题，仅在明确授权范围与隔离环境中验证，并按对应披露流程处理。真实协议调用成功并不证明操作得到授权。
新机会的模板与历史案例分开。历史标签不能自动成为当前信号；实验结果也不能自行触发交易。资金、账号、协议授权与结算条件要在每次实际使用时单独复核。
## 运行本地工具
以下保留 Python 底层命令作为接口参考；本地日常使用上面的 JS/npm 入口。SQLite 后端仅依赖标准库，PostgreSQL 后端另需 requirements-db.txt 中的 psycopg。均不需要钱包或交易密钥。
```powershell
python research-workbench/workbench.py init
python research-workbench/workbench.py collect
python research-workbench/workbench.py inbox
python research-workbench/workbench.py report
```
第一次成功采集建立基线，历史条目不会被当成刚出现的机会；以后运行才比较新增与修订。使用 inbox --include-baseline 可查看这部分历史内容。cadence_hours 只控制本次运行哪些源到期，不会让程序自己定时启动。强制检查使用 collect --force。
手工收藏一个已读来源：
```powershell
python research-workbench/workbench.py add --title "CBB HIP-3 历史复盘" --url "https://www.techflowpost.com/en-US/article/33704" --note "历史自述；对应 cases/001-cbb-hip3.md；不是当前信号"
```
从 inbox 取得真实条目 ID，下面以 12 为示例，使用时替换：
```powershell
python research-workbench/workbench.py review 12 --status shortlist --note "需核对规则生效时间与完整资金成本"
python research-workbench/workbench.py review 12 --status archive --note "只描述已有服务报酬，未证明额外优势"
python research-workbench/workbench.py report
```
报告位于 reports/latest.md；业务状态存入当前选定数据库，data/research.db 是保留的 SQLite 文件。成功解析的 feed/page 响应按 SHA-256 存入 data/snapshots；feed 快照不等于文章全文。init 不清空已有状态，PostgreSQL 建表使用显式 migrate。当前数据库请按上方 backup-pg 流程备份；复制工作目录不会包含 Docker 卷内的 PostgreSQL。data 和 reports 默认不进入 Git，不在研究资料中保存钱包密钥、会话 cookie 或私人账户凭证。
## 从 shortlist 接到实验文件
假设你选中一条线索，先复制模板，填入真实 inbox ID 和关联案例。以下文件名是示例，已有同名文件时换新编号，避免覆盖历史笔记。
```powershell
Copy-Item -LiteralPath research-workbench/templates/HYPOTHESIS.md -Destination research-workbench/hypotheses/001-settlement-window.md
Copy-Item -LiteralPath research-workbench/templates/EXPERIMENT.md -Destination research-workbench/experiments/001-settlement-window.md
```
假设卡写“何种结算延迟会消除折价收益”；实验卡记录输入和费用条件。运行后将结论、输出路径和停止原因回写两张卡，再用 review 给原始条目补上卡片路径并归档或保留候选。inbox 状态只管理阅读队列，假设/实验进度保存在文件中，不会自动同步。
已附一个无需联网的入门实验：
```powershell
python research-workbench/experiments/001-evidence-timing/replay.py
```
它用合成数据演示未来信息和乱序到达如何误导研究，生成 result.json；不模拟任何人的实际收益。先读该目录 README，预测答案再运行。
## 怎样复用现有项目
原套利引擎已移动到 [strategies/entropy-arbitrage](../strategies/entropy-arbitrage/README.zh-CN.md)，仅作为学习 demo。其 main.py 的 --record-only 入口提供只读行情采集；entropy_arb/recorder.py 将每秒顶层盘口样本聚合为分钟 CSV。研究工作台的日常命令不启动该 demo。
当前分钟 CSV 没有完整订单深度、逐条 WebSocket 消息和真实成交回执，不能证明新闻策略的毫秒优势，也不能精确还原大额订单成交。当前连接 freshness 也不等于每个价位刚被更新，研究时要另辨接收心跳、盘口更新时间与事件时间。
选择套利方向时，可解释一次价差来自计价币种、合约权利、延迟、费用还是流动性。选择天气或社交媒体方向时，可先验证一种预测方法是否优于预先指定的基准。每次保存观测区间、预测时点、市场标识、规则版本和数据质量说明；评价预测质量与评价交易收益分开进行。
后续按需要增加原始消息 JSONL、断线/丢包检测、只读链上事件采集与固定输入回放。多市场实盘执行、持续运行、推送通知和付费信息源属于后续部署工作，不是当前已启用能力。
## 这个月先完成什么
第 1 周：运行工具，精读种子案例中的两个；能区分一手来源、本人自述和缺失证据。
第 2 周：从任意策略方向选一个机制，写首张假设卡；说明输入、预测/决策时点、基准与证伪条件，涉及交易时补齐权利、资金流和结算过程。
第 3 周：完成一个可重复的小实验，记录费用、时间、缺失数据与反证。
第 4 周：用周复盘删掉无效来源和假设，整理一个失败模式及其下次监控条件。验收标准是形成一次完整研究闭环，而不是实现盈利。

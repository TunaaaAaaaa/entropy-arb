## PostgreSQL 迁移实施计划
日期：2026-09-08。状态：本地核心迁移已实施，默认后端已切换 PostgreSQL；以下保留设计与验收要求，文末记录实际结果和边界。
目标：统一管理当前业务状态、历史证据及研究结果，保留证据文件，并能够从历史版本复现研究判断。
## 已核对的基础
现有工作台使用 Python SQLite 接口；JS 爬虫通过 import_documents.py 入库。npm 入口已经存在。实施时保留 JS 启动方式，初期保留 Python 数据访问层，避免数据库迁移和语言重写同时发生。
上次实际盘点：sources 19、items 96、revisions 96、reviews 2、source_fetches 5、crawled_documents 3；正文文件 2 份、案例 5 张、合成实验 1 个、分钟行情 1177 行。正式迁移前必须重新盘点，不能把这些数量作为永久常量。
初始检查时 Docker Engine 不可连接；用户启动 Docker Desktop 后已恢复，本次 PostgreSQL 18.6 容器启动并通过健康检查。使用容器内 pg_dump/pg_restore，不依赖本机 psql。
## 架构决定
使用一个 PostgreSQL 数据库，分 ops、evidence、research 三个 schema；schema 是逻辑分组，不是资源隔离。第一阶段不拆成多个数据库，不引入消息队列、向量数据库或行情专用数据库。
本地开发优先 Docker Compose，PostgreSQL 18 稳定版本，实施时固定镜像版本与 digest；端口仅绑定回环地址，凭据置于 Git 忽略的本地配置，持久卷独立于容器。云端数据库部署不属于本计划首轮切换。
使用 psycopg 3 的连接与参数化查询；SQL 版本迁移由唯一执行入口管理，记录版本、校验和与执行时间，不在每次普通连接时隐式建表。所有命令由 npm/Node 入口启动。
现有 SQLite 后端在迁移期保留用于对照；采用一次性维护窗口切换，不做长期双写。
## 数据模型

| 分组 | 主要实体 | 管理职责 |
|---|---|---|
| ops | sources、inbox_items、review_events | 来源配置、当前阅读状态、人工审阅历史 |
| ops | crawl_jobs、job_events、migration_runs | 待采集任务、执行状态、重试与迁移运行记录 |
| evidence | documents、document_versions | 稳定文档身份、不可变正文版本、当前版本指针 |
| evidence | observations、artifacts | 每次实际观察/缓存读取/失败及文件路径、哈希、格式 |
| evidence | inbox_document_links | 一个文档可关联多个来源条目，不把 URL 相同等同于来源相同 |
| research | records、record_versions、evidence_links | 案例/假设的当前状态和版本，以及支持、反驳或背景证据 |
| research | experiment_runs、datasets | 实验输入、代码版本、结果、数据集身份与文件清单 |

抓取任务和观察分开：任务可以重试，每次实际尝试有自己的记录；新系统为失败尝试生成 ID。历史资料没有的重试细节不补造。
documents 保存规范化 URL 与原始 URL。每个正文版本记录完整文本、来源发布时间、提取器版本、证据类型以及原始文件关联；原始 HTML/JSON 字节不作为 JSONB 的替代品。
JSONB 只放来源特有的附加字段；核心身份、时间、状态、哈希和外键用固定字段。URL 规范化策略版本化，站点规则不明确时不合并文档。
正文版本去重使用稳定身份、内容哈希、来源元数据与提取器版本；采集时间不进入正文内容去重键。内容相同的再次采集新增 observation，复用版本；原始响应变化但提取文本相同仍保留原始证据关联。
案例内容与人工摘要不被爬虫覆盖。研究结论必须引用 document_version_id，不能只引用“当前文档”；未取得正文的外部链接允许登记为 unresolved_reference，不伪造证据版本。
## 时间与数值约定
区分 event_at、published_at、observed_at、effective_at、recorded_at；已知绝对时间使用 timestamptz。缺失时间保留 NULL；无时区的历史字符串保存原文和不确定性标记，不擅自解释成 UTC。
缓存命中创建 cached 访问记录，保持原观察时间；迁移时间只写 imported_at，不替代原始时间。历史错误只有最近尝试时间时，按现有精度保存。
金额、价格、数量按字段语义使用 NUMERIC 或精确文本，禁止迁移时经浮点中转。现有 CSV 已有的舍入误差无法恢复；保留原文件及字段精度说明。
## 现有数据迁移映射

| 现有来源 | 目标与规则 |
|---|---|
| sources.json + sources | 配置值以 sources.json 为初始依据；SQLite 的运行状态单独迁移；manual-user 保留；不一致输出差异报告 |
| items | ops.inbox_items；保留旧 ID 映射、baseline、状态、人工文本与来源身份 |
| revisions | 条目文本修订历史；不是网页正文版本，禁止混为一类 |
| reviews | ops.review_events；顺序、备注与状态迁移完整保留 |
| source_fetches + snapshots | evidence.observations + artifacts；保留原采集时间与响应哈希 |
| crawl/documents + raw | evidence.documents、document_versions、artifacts；校验所有现存文件与引用 |
| crawl/runs | 有可辨认证据的观察与失败历史；按 run ID 和结果序号幂等导入，不重复复制正文 |
| crawled_documents | 最新状态视图的输入及历史补缺；已有 run 记录不重复计数，失败 URL 即使无 item_id 也保留 |
| manual/ 旧采集 | 按文件哈希登记；与新抓取内容相同但观察时间不同，不删除早期观察证据 |
| cases/001…005 | research.records 与初始版本；保留原文和文件哈希，只导入已有结构信息；未核实金额不能变成事实字段 |
| 实验 events.json/result.json | datasets、experiment_runs；标记 synthetic，关联输入哈希与代码；缺失的历史 Git 版本保持未知 |
| 两份 minutes.csv | datasets 登记文件、行数、时间范围、字段与已知市场身份；未知交易对保持未知；首轮不逐行搬入业务库 |

排除：crawl/cache、可重生成日报、node_modules、临时锁、重复操作说明。engine.log 继续作为诊断日志管理；首轮不全文入库。
现有 Markdown 案例保留为迁移源与过渡期阅读文件；切换后数据库版本为研究内容真源，Markdown 为导出物。迁移过渡期若文件变化，按新版本明确导入，禁止静默互相覆盖。
## 实施顺序与交付物

| 阶段 | 工作 | 验收门槛 |
|---|---|---|
| 1 环境与保全 | Compose、配置样例、JS 数据库入口、一致性备份工具、文件清单 | PostgreSQL 可连接；原 SQLite 与证据备份可在独立目录恢复，哈希和计数一致 |
| 2 模型与访问层 | SQL 迁移、外键/唯一约束、存储接口、SQLite 兼容层 | 新库可重复部署；普通连接不改 schema；关键约束和事务回滚测试通过 |
| 3 导入与核对 | 只读导出、幂等导入、旧新 ID 映射、时间异常与缺文件报告 | 重跑不复制实体；条目、审阅、版本、证据逐项可追溯；差异均有明确解释 |
| 4 采集与查询接入 | collect、crawl、inbox、review、report 切换接口；正文查询与版本对比 | 新库完整跑通；缓存不伪造抓取；失败不覆盖成功；并发相同任务无重复入库 |
| 5 研究内容管理 | 案例/假设版本、证据关联、实验登记、Markdown 导出 | 能查询一个机制的材料、引用版本、反证与实验；修改结论仍可还原旧版本 |
| 6 演练与切换 | 再次冻结写入、最终备份与导入、恢复测试、统一后端配置 | 原数据保留；全链路验收通过；失败回退路径已验证 |

阶段 4 的首次检索使用标题/正文/作者/来源/时间过滤；中文子串检索先保证正确性，规模增长后评估 pg_trgm 或中文分词。不能把默认英文全文检索当作中文方案已完成。
按功能阶段形成可审阅 commit；不得以“导入数量相同”代替完整性验证。当前实施情况见下方记录。
## 迁移校验与恢复
先验证当前依赖测试继续通过，再增加 PostgreSQL 集成测试：同 URL 多来源、重复抓取、日期无时区、缺文件、篡改文件、导入中断、重复导入、并发更新、旧证据引用和连接失败。
正式导出前停止工作台采集/审阅写入；使用 SQLite backup API 取得一致快照，再复制引用文件并生成哈希清单。新旧表结构不同，验收按实体映射、文本哈希、引用完整性与业务状态核对，不要求所有目标表行数等于旧表。
PostgreSQL 用 pg_dump 与证据文件清单共同备份；在独立数据库恢复后核对引用和样例查询。仅备份数据库或仅 push Git 都不算完成。
切换前失败可继续使用原 SQLite。切换后若已经产生新写入，先停止写入并导出增量，回放到旧后端且验证后才能回退；禁止直接切回旧库丢弃新研究记录。
建立周期备份能力但不自动创建后台任务；首次切换必须先完成一次手动备份/恢复演练。
## 后续扩展触发条件
大批量行情分析出现性能瓶颈时，再引入 Parquet 和分析引擎；需要与交互业务隔离资源时再拆分析库。文档/观察表的数据量与查询计划证明有必要时再分区。多人或多机访问时部署统一服务，避免把数据库文件当共享文件同步。
实施保护范围：优先保全原始证据及研究成果；现有交易模块不参与此次数据库切换。
## 本次实施记录
已完成本地环境、显式 SQL 迁移、旧数据导入、采集接口接入、研究版本管理、备份恢复和默认后端切换。管理入口为 npm run db --；日常入口保持 npm run workbench -- 和 npm run crawl --。
正式库 entropy_research_live；最初的 entropy_research 留作演练库。Docker 端口仅绑定 127.0.0.1:55432，独立卷 entropy-research_postgres_data；连接凭据和后端选择只保存在 data/local/，不提交 Git。
SQLite 最终备份：data/backups/20260908T134704199589Z。原六表逐字段验证通过（19/96/96/2/5/3），重复导入通过，配置差异为零。五张案例、两份 1177 行 CSV 数据集索引和一个合成实验已登记；未建立任何虚构假设或盈利结论。
正式 PostgreSQL 切换前备份：data/pg-backups/20260908T134738301827Z；恢复库 entropy_restore_73156d4b4c7e，23 张表内容哈希和 52 个文件校验一致。备份目录包含 manifest.json、database.dump、files/ 和 restore-result.json。
保留限制：历史缺失时区没有猜测；图片/OCR 与大批行情分析未加入；既有案例引用保留 unresolved_url，需人工确认所用正文版本；中文检索当前为子串查询。任务事件在完整回执入库时保存，尚无崩溃中途事件恢复与分布式调度。
恢复已验证为完整 PostgreSQL 备份恢复至独立库，不包括 PostgreSQL 新增数据反向迁回 SQLite。不能直接切回旧 SQLite 丢弃新增记录；优先恢复 PostgreSQL。备份目前均在本机，没有开启异地或自动定时备份。云端部署和应用镜像构建仍为后续工作。

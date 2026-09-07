## CASE-004：Tree of Alpha 的 Coinbase 安全披露
漏洞报告：2022-02-11；Coinbase 公告：2022-02-18；整理：2026-09-07。
证据：Coinbase 官方确认漏洞和 25 万美元奖励；人物归属与研究经历见本人采访。
来源：[官方复盘](https://www.coinbase.com/blog/retrospective-recent-coinbase-bug-bounty-award)、[本人访谈](https://www.theblock.co/news/markets/2022-02-20-a-qa-with-the-researcher-who-identified-coinbases-market-nuking-trading-bug-134856)。
## 事实与边界
这是交易接口的逻辑校验缺陷，已修复；奖励来自负责任披露。采访中他称，一些安全发现发生在寻找可交易信息的研究过程中。不能将历史测试方式或支付结果当成今天的测试授权。
## 可迁移假设
局部检查通过不代表端到端约束成立。研究者要能说明资产、账户、权限与账本之间应该始终保持什么关系。
## 研究任务
在自己编写的玩具账本中，用整数或 Decimal 表示资产数量，为资产类型、所有权与借贷记账写不变量。仅在自有模型或明确授权隔离环境中验证。
## 变现与证伪
安全发现转入对应项目的授权范围、证明和披露流程；真正漏洞、有效报告与应付奖金额度仍是不同问题。确认范围、重复发现和奖励资产口径后再评价预期收入。
机制标签：端到端约束；记账；授权安全研究；负责任披露。
下一次监控：官方已修复事件与基础合约版本变化（sources 中 openzeppelin_releases、immunefi_rules），抽象失效约束。研究真实项目之前单独确认当期授权范围；发布了新版本本身不证明存在漏洞。

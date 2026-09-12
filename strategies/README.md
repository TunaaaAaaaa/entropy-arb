## 策略子项目
每个策略或监控子项目在这里拥有独立目录，与其他策略平级。

| 子项目 | 用途 | 当前状态 |
|---|---|---|
| [entropy-arbitrage](entropy-arbitrage/README.zh-CN.md) | 原套利引擎 | 学习 demo |
| [crypto-news-bot](crypto-news-bot/README.md) | RSS 新闻分级、飞书 / 企业微信长连接、SQLite 按渠道去重 | V0.2；[最小闭环](crypto-news-bot/experiments/001-rss-feishu-smoke/README.md)、[长连接实验](crypto-news-bot/experiments/002-wecom-long-connection/README.md) |

新策略按需要创建，不预先建立没有实现的天气或社交预测空壳。
## 目录约定
一个策略拥有自己的 README、依赖、JS 启动入口、源码、tests/ 和 experiments/。需要容器时才添加自己的 Dockerfile/compose.yaml，并使用唯一 Compose 项目名、输出目录和主机端口。当前 demo 没有容器，也不加入研究数据库的 Compose 启动流程。
experiments/<experiment-id>/ 放实验定义、代码和输入清单；data/runs/<run-id>/ 放某次运行的参数、结果和日志。原始大文件及私人配置不进入 Git。
研究工作台共用案例、假设与证据；策略代码不得导入另一个策略的内部模块。先出现真实复用需求，再提取公共组件。
## 结果约定
实验结果应记录 strategy_id、hypothesis_id、experiment_id、run_id、代码版本、输入哈希、参数、时间范围、模式（合成/回放/模拟/实测）、评价指标和结论。预测质量与交易收益分开；没有成交模型时不能填写已实现盈利。
这是新策略的设计约定，通用结果导入器尚未实现。现有工作台 import-research 仍只支持旧入门实验格式，不能直接扫描所有策略实验。新闻机器人先保存独立 JSON 验收记录与 SQLite 推送历史；不接入旧实验导入器，也不将模拟消息作为真实新闻证据入库。
现有 case 表示来源案例；自己的测试使用 experiment，重复执行使用 run。

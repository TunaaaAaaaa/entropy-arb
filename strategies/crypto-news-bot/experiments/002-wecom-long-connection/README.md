## EXP-002：企业微信长连接与双渠道投递
strategy_id：crypto-news-bot；experiment_id：002-wecom-long-connection。
目的：验证 Bot ID / Secret 认证、主动群推送、心跳、重连、群 chatid 发现，以及单渠道失败时不重复投递成功渠道。
## 合成测试
在仓库根目录运行 npm run test:news。新增测试通过真实本机 WebSocket 服务发送协议帧，确认只有正确 req_id 的成功业务回执才记为成功；错误回执、超时、无关回执、认证拒绝都不会误判。关闭连接和心跳超时后应重新认证；退出时应关闭线程。
另使用独立 SQLite 验证：飞书成功、企业微信失败后，下一轮只重试企业微信；新增目标群会建立独立投递状态；旧 V0.1 飞书记录不会误记为企业微信投递。所有测试使用假凭据与假消息，不连接真实企业微信服务。
2026-09-12 首次测试结果：全部 75 项通过（包含原有测试与本次新增测试）。
## 真实联调
步骤见 [企业微信指南](../../WECOM.md)。依次完成认证、在目标群 @机器人取得 chat_id、发送一条测试消息，再启用新闻投递。结果保存在 data/runs/wecom-verification.json，不进入研究工作台的真实新闻证据库。
2026-09-12 17:09（Asia/Shanghai）真实认证通过：使用本地 config.yaml 中的 Bot ID、Secret 运行 npm run news:wecom，企业微信返回认证成功，命令退出码为 0。随后群发现命令也通过认证；当时尚未配置 chat_id。认证检查不会发送可见消息。
2026-09-12 17:19（Asia/Shanghai）真实主动群推送通过：将用户从群回调中取得的目标 chat_id 写入本地 config.yaml，运行 npm run news:wecom -- --send-test。仅发送 1 条带“企业微信长连接测试”字样的消息，接口返回成功回执，命令退出码为 0；本地 data/runs/wecom-verification.json 中 authenticated 和 send_confirmed 均为 true。本次没有运行 RSS 新闻推送；消息在群内的实际展示仍可由用户核对。
此前飞书真实联调已成功：2026-09-12 11:09（Asia/Shanghai），发送 1 条新闻、入库 1 条，第二轮重复跳过 1 条。

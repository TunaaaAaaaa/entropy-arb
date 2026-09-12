## 企业微信智能机器人：长连接接入
目标：向指定企业微信群主动推送筛选后的新闻。使用智能机器人的 API 模式 / 长连接，默认端点为 wss://openws.work.weixin.qq.com；无需在本机提供公网回调服务器。
## 1. 填写机器人凭据
在企业微信创建支持长连接的智能机器人，取得 Bot ID 和 Secret，并将机器人加入目标群。把凭据填入本项目的 config.yaml，不要填到 config.example.yaml：
```yaml
notifiers:
  wecom:
    enabled: false
    bot_id: "填写 Bot ID"
    secret: "填写 Secret"
    chat_id: ""
    ws_url: "wss://openws.work.weixin.qq.com"
    timeout_seconds: 10
    heartbeat_seconds: 30
```
保留其他配置项，包括已有飞书 Webhook。先保持 enabled: false，方便在取得目标群标识前联调；该设置只控制新闻主流程是否使用企业微信，显式联调命令仍会连接。
使用同一个 Bot 时，只启动一个连接进程。认证被拒后本进程停止重试；修改凭据后重新启动。
## 2. 检查认证并获取目标群标识
在仓库根目录运行：
```powershell
# 只检查长连接认证，不发送可见消息
npm run news:wecom
# 保持连接 60 秒；这段时间内去目标群 @机器人一次
npm run news:wecom -- --discover
```
第二条命令从群消息回调中读取 chatid，在终端显示并保存到子项目 data/runs/wecom-groups.json。需要更多时间时添加 --seconds 120。若发现多个群，请核对自己刚刚 @机器人的目标群，再将对应标识写入 config.yaml 的 chat_id。
只记录群标识，不保存群消息正文、不自动回复，也不自动把任何来信群绑定为新闻推送目标。主动发送所需的是群 chatid，Bot ID 本身不能代替发送目标。
## 3. 发送测试消息
填写 chat_id 后运行：
```powershell
npm run news:wecom -- --send-test
```
仅向所配置的群发送一条带“企业微信长连接测试”字样的消息，不抓取 RSS，不写入新闻已推送表。结果保存到 data/runs/wecom-verification.json；接口成功回执不代表成员已读，请在目标群核对消息。
退出码：0 表示认证/发送/发现任务成功，1 表示连接或投递失败（或发现期间没有群回调），2 表示配置错误。
## 4. 接入新闻推送
验证成功后将 enabled 改为 true：
```powershell
# 一轮新闻抓取和推送
npm run news:once
# 进程持续运行，按配置每 10 分钟抓取
npm run news:start
```
飞书和企业微信各自记录成功投递；某个渠道失败时不会重发已成功的渠道。企业微信连接在整个进程中复用，定时抓取间隙也保持心跳；单轮运行结束、联调命令退出或 Ctrl+C 时关闭连接。
## 协议与当前边界
连接后发送 aibot_subscribe，body 中带 bot_id 和 secret；只有对应请求的 errcode=0 才算认证成功。通过 JSON ping 保活，断线后按 1、2、4 秒逐步退避重连，上限 30 秒，并重新认证。消息使用 aibot_send_msg，body 含 chatid 和 markdown；等待同 req_id 的业务回执确认成功。发送超时或失败不会在传输层自动重发。
本实现使用 websockets 的同步客户端和一个接收线程，按企业微信团队公开的[认证、心跳及回执协议](https://github.com/WecomTeam/wecom-aibot-python-sdk/blob/master/aibot/ws.py)实现需要的子集；[主动发送接口](https://github.com/WecomTeam/wecom-aibot-python-sdk/blob/master/aibot/client.py)说明了 userid 与群 chatid 的区别。
为保持消息长度可控，超过约 4 KB 时压缩正文并保留末尾新闻链接；极长链接无法完整保留时会拒绝发送并记录失败。不接入自动对话、文件下载或 AI 回复。测试仅覆盖本机模拟服务；未填写真实 Bot ID、Secret 和 chat_id 前，不能宣称企业微信实际投递已通过。

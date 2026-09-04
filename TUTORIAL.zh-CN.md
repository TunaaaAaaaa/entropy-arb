# entropy-arb 学习教程（中文）

本教程分两部分：

1. **学习项目构成** —— 用一张“数据流地图”看懂每个文件在做什么，以及它们如何连成一个套利机器人。
2. **学习如何运行和改进** —— 从零开始安装、采集数据、分析阈值、实盘运行，并给出“安全地改代码”的路线图和练习。

> 注意：这不是投资建议。本机器人连接真实交易所且没有模拟盘，`--record-only` 之外的运行都会发真实订单。请从小仓位开始。

---

## 第 1 部分：学习项目构成

### 1.1 用一句话概括项目

`entropy-arb` 是一个双交易所永续合约吃单套利机器人：

- 一条腿固定是 **Entropy**（Hyperliquid 上的 `io` builder dex）；
- 另一条腿（对冲腿）由 `--hedge` 指定，三选一：
  - `lighter`：Lighter 主网（USDC）
  - `lighter-rh`：Lighter Robinhood 链（USDG）
  - `tradexyz`：Hyperliquid 上的 trade.xyz dex

它的赚钱方式是：同一个永续品种在两个交易所价格出现偏差时，同时**在贵的交易所卖出、在便宜的交易所买入**，赚取价差；仓位基本 delta 中性，等溢价回归后反向平仓。

### 1.2 最重要的抽象：三层信息

学习代码前先分清这三类信息，它们存放在不同地方，这是本项目刻意的设计：

| 类别 | 存放位置 | 例子 | 能否提交到 git |
|---|---|---|---|
| 策略与风控 | `config.yaml` | 阈值、仓位上限、手续费、冷却时间 | 可以（但要自己填） |
| 密钥 | `.env` | Hyperliquid agent 私钥、Lighter API 私钥 | **绝不能** |
| 交易哪个市场 | 每次启动的命令行 | `--symbol SNDK --hedge lighter-rh` | 不存文件 |

这样做的好处：配置可以安全地分享和审查；密钥不会混进策略文件；交易品种必须“显式决定”，不会因为忘了配置而交易错误市场。

### 1.3 目录地图

```
main.py                         入口：解析命令行、加载配置、启动/停止引擎
entropy_arb/config.py           YAML + .env 的契约、校验、dataclass
entropy_arb/book.py             订单簿状态，以及“吃多深、能吃多少”的数学
entropy_arb/feeds.py            两个官方 websocket 行情消费者
entropy_arb/venue_hl.py         Hyperliquid 系交易所适配器（Entropy、tradexyz）
entropy_arb/venue_lighter.py    zkLighter 系交易所适配器（主网、Robinhood 链）
entropy_arb/engine.py           策略主循环、执行、库存阶梯、净敞口对冲、对账
entropy_arb/recorder.py         每秒采样盘口，每分钟写一行 CSV
entropy_arb/dashboard.py        Rich 终端仪表盘
tools/analyze.py                读取分钟 CSV，生成阈值建议
tests/                          无网络的单元测试，用 pytest 运行
```

### 1.4 运行时数据流

看懂这张图，就读懂了 80% 的代码：

```
main.py
   │  解析 --symbol / --hedge / --record-only / --cn
   ▼
config.load_config(config.yaml + .env)
   │  校验 YAML 键名；生成 Config / VenueConf 对象
   ▼
Engine.run()
   ├── 创建 HLVenue / LighterVenue
   ├── 每个 venue.load_market()：找到真实交易对、步长、最小单
   ├── 启动行情任务：feeds.HLBookFeed / LighterBookFeed
   │        └── 写入 OrderBook
   ├── 启动 recorder：每秒读 OrderBook → logs/minutes.csv
   ├──（实盘）启动策略循环 _strategy_loop()
   └──（实盘）启动对账/权益/保活循环
```

策略循环的“心跳”是：

```
行情 websocket 更新
   → engine._update_evt.set()
   → engine._evaluate()
   → engine._scan() 检查两个方向
        SELL entropy：hedge 买盘 vs entropy 卖盘
        BUY  entropy：entropy 买盘 vs hedge 卖盘
   → plan_arb() 按真实盘口逐档计算可成交数量和预期收益
   → 信号持续 premium_persist_sec 后触发
   → 同时给两条腿发 taker 订单
   → 更新本地仓位/现金；若两腿成交不等则 net-delta 对冲
   → 定期 reconcile 对齐链上真实仓位
```

### 1.5 每个核心文件的“角色说明书”

#### `entropy_arb/config.py`

- 定义 `HEDGE_VENUES`、`LIGHTER_PROFILES`（主网 vs Robinhood 链的 REST/WS/chain_id）。
- 定义 `Config`、`VenueConf`、`HLCreds`、`LighterCreds`。
- 用 `_SCHEMA` 做严格校验：YAML 里出现未知键会直接报错，防止“打错字后静默忽略”。
- 读取 `.env`，把密钥接到对应的腿；`--hedge tradexyz` 时默认两条 Hyperliquid 腿共享账户。

学习重点：本项目把**“市场选择”从配置文件里移到了命令行**，所以 config 中不允许出现 `symbol` / `hedge_venue` 等键。

#### `entropy_arb/book.py`

- `OrderBook`：用 `dict` 保存 bids/asks；`apply_hl()` 处理 Hyperliquid 全量快照，`apply_lighter()` 处理 Lighter 快照+diff。
- `crossable_base()`：从买一/卖一开始逐档向下吃，每一档都必须仍然满足“扣手续费后超过阈值”。
- `plan_arb()`：把可套利深度、`take_fraction`、单笔名义上限、最小下单量合成一个 `ArbPlan`。

学习重点：所有交易决策都用**真实可成交的订单簿**，而不是中间价拍脑袋。

#### `entropy_arb/feeds.py`

- `LighterBookFeed`：订阅 `order_book/{market_id}`；对 diff nonce 做连续性检查，缺 diff 就丢弃当前簿并重新订阅，避免基于“假盘口”交易。
- `HLBookFeed`：订阅官方 Hyperliquid `l2Book`，发客户端 ping 保活。
- 两者都通过 `notify()` 唤醒引擎。

学习重点：行情模块只负责把 websocket 消息变成 `OrderBook`，不关心交易；因此引擎可以用同一套逻辑面对不同交易所。

#### `entropy_arb/venue_hl.py` / `entropy_arb/venue_lighter.py`

- 两个适配器向引擎暴露**相同接口**：`load_market()`、`start_tasks()`、`send_taker()`、`fetch_position()`、`fetch_equity()`、`px_round()`、`ready_to_trade()` 等。
- `send_taker()` 都返回统一形状：
  `{"status", "filled_base", "avg_px", "err", "unresolved"}`
- 实盘才需要签名 SDK；`--record-only` 只需要 `aiohttp` + `websockets`。
- Hyperliquid 用 IOC 限价单同步结算；Lighter 用带均价保护的市价单，在鉴权 websocket 上异步确认成交。

学习重点：要增加新交易所，本质就是再实现一套同样的 `send_taker()` 与账号查询接口。

#### `entropy_arb/engine.py`

这是“大脑”：

- `_scan()`：按两个方向扫描，检查盘口新鲜度、仓位上限、限频、库存阶梯。
- `_armed` + `premium_persist_sec`：信号必须持续一段时间才触发，过滤瞬时假信号。
- `_execute()`：同时向两条腿发单，处理部分成交，更新本地状态。
- `_inv_add_bps()`：库存阶梯。当某腿仓位接近上限时，同方向加仓需要额外溢价。
- `_maybe_hedge()` / `_hedge()`：两腿成交不对等导致净敞口过大时，用 reduce-only 单对冲。
- `_reconcile_*()`：定期用链上/交易所真实仓位修正本地估算。
- `_status_loop()`：每 30 秒输出一行状态日志。

学习重点：不要把“信号”和“执行”混在一起看。信号主要来自 `config.yaml` 中的阈值；执行和风控则集中在这里。

#### `entropy_arb/recorder.py`

- 每秒调用 `sample()`，两本订单簿都新鲜时记录：`entropy bid/ask`、`hedge bid/ask`、中间价溢价、两个方向的可成交 edge。
- 每分钟滚动写一行 `logs/minutes.csv`。
- 即使没有密钥、不交易，也能采集数据。

#### `entropy_arb/dashboard.py`

- 读取 `Engine` 的实时状态，用 Rich 画成面板。
- `--cn` 时通过 `_ZH` 字典翻译 UI。
- 只读引擎状态，不改策略逻辑。

#### `tools/analyze.py`

- 读取 `minutes.csv`，计算溢价均值/中位数/分位数。
- 输出候选带宽的触发频率（扣掉 `--fees-bps` 后的净触发）。
- 输出可直接粘贴的 `thresholds:` 建议。

### 1.6 策略核心：三个数字

整个“信号”不是复杂的模型，而是 `config.yaml` 里的三个数：

```
premium_bps = (Entropy 价格 / 对冲腿价格 − 1) × 10_000

卖出 Entropy / 买入对冲腿： 可成交 premium ≥ midline + upper
买入 Entropy / 卖出对冲腿： 可成交 premium ≤ midline − lower
```

- `midline_bps` 是溢价长期中枢。跨所溢价不一定是 0（预言机不同、计价币不同、新上市溢价等），所以要用采集数据来定。
- `upper_bps` / `lower_bps` 是中枢两侧的入场带宽。
- 门槛已经扣掉两边手续费；引擎会在阈值之上另加手续费。因此一次完整往返后，净赚至少 `upper + lower` bps。

“为什么买腿阈值可能是负数？”这是新手最常问的问题。举例：如果 Entropy 长期比 Hedge 贵 5 bps（`midline_bps: 5`），那么当市场溢价回到 0 时，买入 Entropy 相对它自己的“正常中枢”就是便宜了 5 bps，正好用来平掉之前在 `midline + upper` 卖出的仓位。所以**中枢填错会变成亏损策略**：先测量，再交易。

### 1.7 配置键速查

| 想控制什么 | 键 | 说明 |
|---|---|---|
| 策略阈值 | `thresholds.*` | 中线与上下带宽，用 `tools/analyze.py` 得出 |
| 仓位上限 | `entropy/hedge.max_position_usd` | 每条腿最大持仓美元 |
| 单笔大小 | `sizing.take_fraction`、`max_order_notional_usd` | 吃多少深度、单笔名义上限 |
| 库存惩罚 | `inventory.scale_bps`、`floor_frac` | 接近上限后同向加仓要更苛刻 |
| 信号持续时间 | `execution.premium_persist_sec` | 过滤单 tick 假信号 |
| 下单预算 | `*.max_orders_per_min` | 滑动 60 秒内的发单次数预算 |
| 数据采集 | `recorder.enabled`、`recorder.csv` | 默认写到 `logs/minutes.csv` |
| 日志/仪表盘 | `logging.*` | 终端面板、日志文件、成交 CSV |

---

## 第 2 部分：学习如何运行和改进

### 2.1 环境准备

假设你已经在项目目录里（或先 `git clone`）：

```bash
# 1. 创建虚拟环境
python -m venv .venv

# Linux / macOS
source .venv/bin/activate
# Windows Git Bash
source .venv/Scripts/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1

# 2. 安装基础依赖（采集数据 / 跑测试够用）
pip install -r requirements.txt

# 3. 创建本地配置和密钥文件
cp config.example.yaml config.yaml
cp .env.example .env
```

先不要填密钥。`--record-only` 不需要任何密钥。

### 2.2 先跑测试，确认代码健康

```bash
python -m pytest tests/ -q
```

也可以不安装 `pytest`，逐个脚本跑：

```bash
python tests/test_book.py
python tests/test_config.py
python tests/test_engine.py
python tests/test_recorder.py
python tests/test_dashboard.py   # 需要 rich（requirements.txt 已含）
```

### 2.3 第一次运行：只采集数据（不是模拟交易）

> 先明确一个容易混淆的点：本教程里没有“模拟交易/模拟盘/仿真成交”。
> 下面的命令是项目的 **record-only（仅采集）模式**，不是纸上交易。
> 它只是连接两个交易所的**真实行情 websocket**，把盘口数据记录到
> `logs/minutes.csv`；它不会启动策略循环、不会生成订单、不会模拟成交，
> 也不需要 `.env` 密钥。

```bash
python main.py --record-only --symbol SNDK --hedge lighter-rh
```

说明：

- `--symbol` 必须是两个交易所共同交易的品种，例如 `SNDK`。请先确认该品种在 Entropy 与你的 `--hedge` 交易所都存在且状态为 active。
- `--hedge` 三选一：`lighter` / `lighter-rh` / `tradexyz`。
- 在终端会看到 Rich 仪表盘；想用中文加 `--cn`：
  ```bash
  python main.py --record-only --symbol SNDK --hedge lighter-rh --cn
  ```
- 如果不想要仪表盘（例如要写进日志文件/后台运行）：
  ```bash
  python main.py --record-only --symbol SNDK --hedge lighter-rh --no-dashboard
  ```

让它跑至少几个小时，最好一整天。按 `Ctrl+C` 会优雅停止并写出最后一个完整/不完整分钟。

运行中你会看到：

```
logs/minutes.csv   # 分钟级盘口数据
logs/engine.log    # 运行日志
```

查看数据列：

```bash
head -3 logs/minutes.csv
```

每行包括：分钟时间戳、两边买一/卖一、中间价溢价的 open/high/low/close/mean/std、两个方向可成交 edge 的 mean/max、以及该分钟有多少秒两边盘口都新鲜（`samples`）。

### 2.4 分析数据，生成阈值建议

```bash
python tools/analyze.py
```

如果对冲腿是 `tradexyz`，传入两边吃单费之和（约 1.0 bps）：

```bash
python tools/analyze.py --fees-bps 1.0
```

如果只想看最近 24 小时：

```bash
python tools/analyze.py --hours 24 --fees-bps 1.0
```

脚本会打印：

- 溢价分布（mean / std / median / p5 / p25 / p75 / p95）；
- 各候选带宽的触发分钟数 / 每天触发次数；
- 一段可直接粘贴的 `thresholds:` 建议。

把建议粘贴到 `config.yaml`：

```yaml
thresholds:
  midline_bps: 5.0     # 示例，用工具实际输出替换
  upper_bps: 4.0
  lower_bps: 3.0
```

然后重新运行测试确保配置仍能加载：

```bash
python -c "from entropy_arb.config import load_config; load_config('config.yaml', '.env', symbol='SNDK', hedge_venue='lighter-rh'); print('ok')"
```

### 2.5 实盘运行

**再次强调：没有模拟盘。** 不带 `--record-only` 就会发真实订单。

1. 安装交易签名 SDK：

```bash
pip install -r requirements-live.txt
```

2. 按 `.env.example` 填写密钥。

   - 如果 `--hedge` 是 `lighter` / `lighter-rh`，填 `LIGHTER_*`。
   - Entropy 腿始终需要 Hyperliquid 的 agent 钱包私钥和账户地址（`HL_PRIVATE_KEY` / `HL_ACCOUNT_ADDRESS`）。
   - `--hedge tradexyz` 默认复用同一个 Hyperliquid 账户；需要分开时再设 `HL_PRIVATE_KEY_XYZ` / `HL_ACCOUNT_ADDRESS_XYZ`。

3. 先把 `config.yaml` 的 `max_position_usd` 调到刚好超过交易所最小名义的很小水平，比如 10–100 美元。

4. 启动：

```bash
python main.py --symbol SNDK --hedge lighter-rh --cn
```

启动时会先拉取两个市场、核对链上起始仓位，然后开始交易。日志中会出现：

- `LIVE — real orders will be sent`
- 每笔 `[ARB]` / `[SETTLED]`
- 对冲 `[HEDGE]`、对账 `reconcile`
- 状态行 `[status]`

### 2.6 日常运维命令

| 场景 | 命令 |
|---|---|
| 后台运行（Linux/macOS） | `nohup python main.py --symbol SNDK --hedge lighter-rh --no-dashboard >> logs/console.log 2>&1 &` |
| 使用自定义配置 | `python main.py --symbol SNDK --hedge lighter-rh --config my-config.yaml` |
| 使用自定义密钥文件 | `python main.py --symbol SNDK --hedge lighter-rh --env-file my.env` |
| 只看日志不占屏 | `python main.py --symbol SNDK --hedge lighter-rh --no-dashboard` |

---

## 第 3 部分：如何安全地改进这个项目

### 3.1 推荐的迭代流程

1. **先看懂一条数据流**：从 `config.yaml` → `engine._evaluate()` → `plan_arb()` → `venue.send_taker()`。
2. **先在“无风险”的地方改**：`tools/analyze.py`、`dashboard.py`、`recorder.py` 不涉及下单。
3. **每次只改一小块**，跑对应测试：
   ```bash
   python -m pytest tests/ -q
   ```
4. **对纯函数写单元测试**：`plan_arb`、`OrderBook.apply_lighter`、`_eff_threshold` 都很容易测试。
5. **跑 `--record-only` 验证**：确认行情、日志、CSV、仪表盘都正常。
6. **最后才用小仓位实盘验证**。

### 3.2 想改进不同地方时，改哪里？

| 目标 | 主要改动位置 | 例子/注意 |
|---|---|---|
| 调策略参数 | 只改 `config.yaml` | 先跑 `tools/analyze.py`，不要拍脑袋 |
| 提高/降低下单频率 | `execution.cooldown_sec`、`*.max_orders_per_min` | 已在配置中 |
| 改变信号数学模型 | `engine._eff_threshold()` / `_scan()` | 同时更新测试和仪表盘显示 |
| 改变套利深度算法 | `book.crossable_base()` / `plan_arb()` | 纯函数，测试覆盖最方便 |
| 增加/修改风控规则 | `engine._scan()` / `_execute()` / `config.py` | 要先在 config 中加入键 |
| 增加行情来源或协议 | `feeds.py` + `book.py` | 可给 `OrderBook` 增加新 `apply_xxx()` |
| 增加一个交易所 | `config.py` + 新 `venue_*.py` | 需要实现与 `HLVenue` / `LighterVenue` 同款接口 |
| 改数据采集内容 | `recorder.py` | 改 `HEADER` 和 `_MinuteAgg`；注意旧 CSV 会被轮转 |
| 加分析指标 | `tools/analyze.py` | 这是最安全的新手练习区 |
| 改仪表盘 | `dashboard.py` | `_ZH` 是中文字典；各 `_panel()` 是渲染入口 |
| 改进对账/故障恢复 | `engine._reconcile_*`、各 venue `fetch_position` | 需要仔细想边界情况 |
| 改进交易成交处理 | `venue_hl.send_taker()` / `venue_lighter.send_taker()` | 涉及真钱，要格外谨慎 |

### 3.3 如果要增加一个交易所，该做哪些事？

本项目把交易所抽象成“适配器”。新增一个交易所大致需要：

1. 在 `config.py` 中扩展 `HEDGE_VENUES`、`LIGHTER_PROFILES`（如果同协议）或增加新类型。
2. 新建 `venue_xxx.py`，实现引擎需要的方法：
   - `load_market()`：解析 symbol、小数位、最小下单量
   - `start_tasks(stop, notify, live)`：启动行情任务、需要时启动成交推送任务
   - `send_taker(...)`：返回统一结果字典
   - `fetch_position()`、`fetch_equity()`
   - `ready_to_trade()`、`px_round()`
3. 在 `engine._make_venue()` 里根据 `vc.kind` 创建对应适配器。
4. 为新适配器写 fake/stub 单元测试，避免依赖真实网络。
5. 更新 README 与配置示例。

### 3.4 新手最适合做的 5 个改进练习

1. **给 `analyze.py` 增加新统计**
   - 例如打印“最差连续亏损区间”“最大连续触发次数”“按小时分组的溢价热力”。
   - 纯读 CSV，安全无风险。

2. **给 `dashboard.py` 增加一个指标**
   - 例如在 Session 面板显示“距离上次成交秒数”或“最近 1 小时触发次数”。
   - 只读引擎状态，不影响交易。

3. **给纯数学加测试**
   - 在 `tests/test_book.py` 中补充：某档深度扣费后不再划算时，`q_max` 应停在该档之前。
   - 在 `tests/test_engine.py` 中补充：`midline_bps` 为负数时，两个方向 `_eff_threshold` 之和仍等于 `upper+lower`。

4. **增加一个配置项并让它在代码里生效**
   - 例如新增 `sizing.max_position_skew_ratio` 或 `execution.max_slippage_usd`。
   - 修改顺序：`config.example.yaml` → `_SCHEMA` → `Config` dataclass → 读取/默认值 → 使用它的模块 → 测试 → README。

5. **让 `--record-only` 也能在断网/缺库时给出更友好的提示**
   - 在 `main.py` 或 `feeds.py` 捕获常见 ImportError / ConnectionError，输出排查清单。

### 3.5 改进时要保持的架构原则

- **配置键必须严格校验**。新增键后同步更新 `_SCHEMA`、`Config`、`config.example.yaml`。
- **密钥不进 `config.yaml`**，只进 `.env`；不要提交 `.env`。
- **行情和交易分离**。book/feeds 只负责维护真实盘口，venue 负责下单和账户。
- **`--record-only` 不应需要签名 SDK 和密钥**。如果改动导致采集模式也要密钥，通常是设计退化。
- **统一 `send_taker` 返回形状**，让引擎不关心底层是 Hyperliquid 还是 Lighter。
- **交易代码要能优雅停机**。引擎会等待在途订单结算；新增任务时也要把 `stop` 事件传下去。
- **先改测试，再改代码**，尤其涉及金额数学时。

---

## 附录：最快上手清单

```bash
# 1) 环境
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
cp config.example.yaml config.yaml

# 2) 测试
python -m pytest tests/ -q

# 3) 采集数据（无密钥）
python main.py --record-only --symbol SNDK --hedge lighter-rh --cn

# 4) 分析并填阈值
python tools/analyze.py
# 编辑 config.yaml 中 thresholds.*

# 5) 实盘（需要 .env 密钥和 requirements-live.txt）
pip install -r requirements-live.txt
# 填写 .env；把 max_position_usd 调小
python main.py --symbol SNDK --hedge lighter-rh --cn
```

祝你学习顺利。记住这个项目的核心心法：**先采集真实数据，再设阈值；先小仓位，再放大；先理解，再改进。**

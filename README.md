# entropy-arb

**[中文文档 / Chinese documentation → README.zh-CN.md](README.zh-CN.md)**

This fork combines a **crypto mechanism research workbench** with the original two-venue perpetual arbitrage engine. The workbench collects public information, preserves evidence, tracks case studies and hypotheses, and links research to reproducible experiments. Its collection commands do not call an LLM or place trades.

## Research workbench

The workflow is: **collect → review → fetch full text → form a hypothesis → test → record evidence and conclusions**. Feed/page monitoring, URL crawling, deduplication, review states, reports, and versioned PostgreSQL storage are implemented. Scheduling, notifications, off-site backups, and automatic research-to-trade execution are not configured.

| Guide | Contents |
|---|---|
| [Workbench guide](research-workbench/README.zh-CN.md) | Daily workflow, case studies, and research templates |
| [Crawler guide](research-workbench/CRAWLER.zh-CN.md) | URL ingestion, cache behavior, extraction, and limitations |
| [Storage and migration](research-workbench/POSTGRES-MIGRATION-PLAN.zh-CN.md) | PostgreSQL migration, verification, and recovery |
| [Sources](research-workbench/SOURCES.zh-CN.md) / [configuration](research-workbench/sources.json) | Collection sources and manual reading lists |
| [Technical roadmap](research-workbench/TECH-ROADMAP.zh-CN.md) | Skills and experiments to develop incrementally |

The detailed guides above are currently in Chinese.

### Setup and daily use

Use the **Node.js/npm entry points** locally. Node.js 22+ and Python 3.11+ are required; the JS launchers invoke the Python storage/workbench code. Set `RESEARCH_PYTHON` if the interpreter is not available as `python`.

```powershell
git clone https://github.com/TunaaaAaaaa/entropy-arb.git
cd entropy-arb/research-workbench
npm ci
python -m pip install -r requirements-db.txt
```

A fresh checkout contains no private database, credentials, or collected history. For an initial SQLite workspace, run `npm run workbench -- init`. The already migrated local installation uses PostgreSQL (`entropy_research_live`); start Docker Desktop and run `npm run db:up` before using it. All following npm commands run from `research-workbench/`.

```powershell
npm run workbench -- collect
npm run workbench -- inbox
npm run crawl -- https://x.com/Web3Feng/status/2097002992755183901
npm run workbench -- report
```

The first collection establishes a baseline; use `inbox --include-baseline` to see historical entries. Source cadence controls which sources are due during a run; it does not schedule future runs. Crawling uses Crawlee/Cheerio, saves full-text evidence and content hashes, and reuses valid cached content unless `--force` is supplied. Individual X posts use a labeled third-party provider. Login-only pages, browser-rendered content, complete account timelines, and image OCR are not supported.

To provision PostgreSQL on a new machine, run `npm run db:setup`, `npm run db:up`, and `npm run db -- migrate`. These prepare the database; they do **not** migrate existing data or select the backend. Follow the [migration guide](research-workbench/POSTGRES-MIGRATION-PLAN.zh-CN.md) to import legacy/research records, back up, verify an isolated restore, and activate PostgreSQL.

With PostgreSQL configured:

```powershell
npm run db -- status
npm run db -- search "Lido"
npm run db -- backup-pg
# Replace BACKUP_DIRECTORY with the directory returned by backup-pg.
npm run db -- restore-pg BACKUP_DIRECTORY
```

Use `document VERSION_ID` to read evidence, `diff LEFT_VERSION_ID RIGHT_VERSION_ID` to compare versions of the same document, and `save-record RECORD_ID FILE --kind hypothesis --status draft` to save a research revision. `link RECORD_VERSION_ID DOCUMENT_VERSION_ID --relation supports` connects a research revision to evidence; `refutes` and `background` are also supported. Markdown edits must be saved through `save-record` to update the database; `export-record RECORD_ID` exports the current revision.

### Data and recovery

| Data | Storage |
|---|---|
| Current sources, inbox, reviews, and collection state | PostgreSQL `ops` schema |
| Document versions, observations, hashes, and evidence references | PostgreSQL `evidence` schema |
| Cases, hypotheses, revision history, datasets, and experiment links | PostgreSQL `research` schema |
| Raw responses, extracted documents, snapshots, and immutable file copies | `research-workbench/data/`, referenced from the database |
| Editable research and experiment inputs | `research-workbench/cases/`, `hypotheses/`, and `experiments/` |
| Quote CSVs and generated reports | `logs/` and `research-workbench/reports/` |
| Local connection/backend settings and backups | `research-workbench/data/local/` and `data/pg-backups/` |

Business state and historical evidence are separated by schema and versioned records within one PostgreSQL database. Large evidence files remain on disk. Back up **both the database and its referenced files**. Runtime data, credentials, reports, and backups are excluded from Git; pushing the repository does not upload them.

`backup-pg` currently targets the local Docker Compose database. `restore-pg` restores into an isolated database and verifies table contents and files. Backups remain local; a Docker volume is not an off-site backup. Cloud deployment still needs persistent storage, an off-site backup policy, and adapted backup execution. The retained `data/research.db` is the old SQLite snapshot: `backup` only backs up SQLite, and switching back to it after PostgreSQL writes would omit newer data.

### Verification

```powershell
npm test
npm run test:db
```

The crawler tests exercise extraction, caching, and failures. Database tests include PostgreSQL integration tests using isolated test databases; they require a running, configured PostgreSQL instance and a database role allowed to create test databases.

## Original trading module

The original engine remains available separately. One leg is always **Entropy**
(the `io` builder dex on Hyperliquid); the other leg — the hedge — is one of:

| `--hedge` | venue | quote | taker fee | protocol |
|---|---|---|---|---|
| `lighter` | Lighter mainnet | USDC | 0 bps | zkLighter ws (diff books, async settle) |
| `lighter-rh` | Lighter Robinhood chain | **USDG** | 0 bps | zkLighter ws |
| `tradexyz` | Hyperliquid trade.xyz dex | USDC | ~1 bps | HL l2Book, sync IOC settle |

> **Referral links** — signing up through these supports this project:
> - Entropy — Tier 4 referral, 100% rebates: <https://entropy.io/?r=yourquantguy>
> - Lighter Robinhood chain: <https://robinhoodchain.lighter.xyz/?referral=QUANT>
> - trade.xyz (Hyperliquid): <https://app.hyperliquid.xyz/join/QUANTGUY>

When the same symbol trades rich on one venue and cheap on the other, the bot
simultaneously sells the rich book and buys the cheap book with taker orders,
carrying a delta-neutral position until the premium reverts and the opposite
crossing unwinds it. Every price it acts on is the **actual order book of the
exchange that will fill the order** — Hyperliquid books come from the official
websocket (`wss://api.hyperliquid.xyz/ws`), Lighter books from Lighter's
official websocket.

While it runs — even with no credentials and no strategy — it records both
books to **1-minute CSV bars**, and the bundled analyzer turns that data into
the three numbers that define the whole strategy.

## The signal

The band is three numbers in `config.yaml`, derived by you from recorded
data:

```
premium_bps = (Entropy price / hedge price − 1) × 10 000

                          ┌──────────────  SELL entropy + BUY hedge
midline + upper  ───────────────────────────────────────────────────
                                       ▲
midline          ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┼ ─ ─   the premium's usual level
                                       ▼
midline − lower  ───────────────────────────────────────────────────
                          └──────────────  BUY entropy + SELL hedge
```

- `midline_bps` — where the premium normally sits. Cross-venue premiums are
  rarely centered at zero (different oracles, different quote assets, listing
  premia), so a zero-centered band would fire one direction only, cap out and
  never unwind. Measure where the premium actually sits and type it in.
- `upper_bps` / `lower_bps` — the entry bands on each side of the midline.

Both hurdles are applied to **executable** prices (entropy bid vs hedge ask,
and vice versa) and are **net of both venues' taker fees** — the engine adds
fees on top before a slice qualifies. The quoted round-trip edge targets
**≥ upper + lower bps after configured taker fees**; realized profit is not
guaranteed and also depends on fills, slippage, funding, and execution failures.

One consequence worth understanding: with `midline_bps: 5`, the buy-entropy
hurdle is `lower − midline`, which can be **negative**. That is intentional —
if entropy is persistently 5 bps rich, buying it at a 0 bps premium is 5 bps
cheap versus its own equilibrium, and that trade is the profitable unwind of
an earlier sell at `midline + upper`. It also means a **wrong midline loses
money**: if you type `midline_bps: 5` while the true premium sits at 0, the
bot happily buys entropy at fair value all day. Measure first, then trade —
that is what the recorder and analyzer are for.

## Trading module quick start

```bash
git clone https://github.com/TunaaaAaaaa/entropy-arb.git && cd entropy-arb
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # data collection needs only this

cp config.example.yaml config.yaml       # the strategy (thresholds, sizing, risk)
cp .env.example .env                     # credentials — required to trade
```

The markets are **not** in the config file — you state them explicitly on
every start: `--symbol` (traded on both venues) and `--hedge` (one of
`lighter`, `lighter-rh`, `tradexyz`; Entropy is always the
other leg).

There is **no paper mode** — the bot either collects data (`--record-only`)
or trades live. Validate with recorded data and tiny position caps, not with
simulated fills.

**1. Collect data first** (no credentials needed):

```bash
python3 main.py --record-only --symbol SNDK --hedge lighter-rh
```

Let it run for at least a few hours (a day is better — premiums have
intraday regimes). It writes `logs/minutes.csv`.

**2. Analyze and set your thresholds:**

```bash
python3 tools/analyze.py
```

It prints the premium distribution, how often each candidate band would have
fired, and a ready-to-paste `thresholds:` block for `config.yaml`.

**3. Go live** — fill in `.env`, install the signing SDKs, and start with
the smallest position caps that clear the venue minimums:

```bash
pip install -r requirements-live.txt
python3 main.py --symbol SNDK --hedge lighter-rh
```

Running without `--record-only` sends real orders immediately once both
feeds are fresh and the band is crossed.

**Dashboard.** On a terminal the bot shows a live Rich dashboard: both
books with age/spread, positions and caps, equity and session PnL, the
executable premium of each direction against its full hurdle (fees and
inventory surcharge included, ● = armed), recorder progress, the last
executions, and a tail of the log (the full log goes to `logging.file`,
default `logs/engine.log`). It works in `--record-only` too. Add `--cn` to
display the dashboard in Chinese. Use `--no-dashboard` for plain console
logs (nohup/systemd — off-terminal runs fall back automatically), or set
`logging.dashboard: false`.

## Data collection & analysis

The recorder runs automatically in every mode (`recorder.enabled: true`).
Once per second it samples both live books; once per minute it writes a row:

| column | meaning |
|---|---|
| `minute_ts`, `time_utc` | minute start (epoch seconds, ISO UTC) |
| `entropy_bid/ask`, `hedge_bid/ask` | last fresh top-of-book of the minute |
| `premium_open/high/low/close/mean/std_bps` | mid-to-mid premium of Entropy over the hedge |
| `sell_edge_mean/max_bps` | executable premium for SELL entropy (entropy bid / hedge ask − 1) |
| `buy_edge_mean/max_bps` | executable premium for BUY entropy (hedge bid / entropy ask − 1) |
| `samples` | how many of the ~60 seconds both books were fresh |

Recorded edges are pre-fee; the analyzer subtracts `--fees-bps` (pass the
**sum** of both venues' taker fees — default 0.0 for the zero-fee venues,
~1.0 with a `tradexyz` hedge) before counting firings, so its table and
suggestions translate directly into config values. `--hours 24` restricts to
recent data; premiums drift, so re-run it regularly and update
`config.yaml`.

## Configuration

Strategy lives in `config.yaml` (validated — unknown keys are startup
errors), credentials in `.env`, and the markets on the command line
(`--symbol`, `--hedge`). Full commented reference:
[config.example.yaml](config.example.yaml). The essentials:

| key | meaning | default |
|---|---|---|
| `thresholds.midline_bps` | premium center (measure it!) | — |
| `thresholds.upper_bps` / `lower_bps` | entry bands (> 0) | — |
| `entropy.dex` | Entropy's dex name on Hyperliquid | `io` |
| `*.taker_fee_bps` | per-venue taker fee | 0.0 (tradexyz hedge: 1.0) |
| `*.max_position_usd` | per-venue position cap | 1000 |
| `*.max_orders_per_min` | per-venue send budget (sliding 60 s) | 120; lighter hedges 30 |
| `sizing.take_fraction` | fraction of crossable depth taken | 0.5 |
| `sizing.max_order_notional_usd` | per-slice cap | 500 |
| `inventory.scale_bps` / `floor_frac` | inventory ladder (extra bps past `floor_frac` of the cap) | 10 / 0.5 |
| `execution.premium_persist_sec` | edge must persist before firing | 0.3 |
| `execution.*` | slippage bounds, timeouts, reconcile cadence… | see file |
| `recorder.*` | minute-data recorder | on, `logs/minutes.csv` |
| `logging.dashboard` / `logging.file` | Rich dashboard on a tty; log file while it runs | on, `logs/engine.log` |

## Credentials (`.env`, live only)

- **Entropy / tradexyz (Hyperliquid)** — create an API ("agent") wallet at
  <https://app.hyperliquid.xyz/API>. `HL_PRIVATE_KEY` is the **agent** key,
  `HL_ACCOUNT_ADDRESS` your main account address. With `--hedge tradexyz`
  both legs share this account by default (one nonce sequence is handled
  internally); set `HL_PRIVATE_KEY_XYZ` / `HL_ACCOUNT_ADDRESS_XYZ`
  to split them. Fund the dex-specific clearinghouses you trade.
- **Lighter** — `LIGHTER_ACCOUNT_INDEX`, `LIGHTER_API_KEY_INDEX`,
  `LIGHTER_API_PRIVATE_KEY`, registered on the **same deployment** as your
  `--hedge` flag (mainnet and the Robinhood chain are separate accounts and
  keys — see [lighter-python](https://github.com/elliottech/lighter-python)).

## How execution works

- Both legs are **taker** orders sent concurrently: Lighter market orders
  with average-price protection settling on the authenticated account
  websocket; Hyperliquid IOC limits settling synchronously (with
  orderStatus polling for unknown outcomes).
- A **persistence gate** (`premium_persist_sec`) arms each direction and only
  fires if the edge survives — one-tick phantoms are filtered.
- **Inventory ladder**: past `floor_frac` of a venue's cap, adding to the
  position requires linearly more edge, up to `scale_bps` extra at the cap.
- **Net-delta hedge**: if legs fill unevenly, the imbalance is immediately
  reduced (reduce-only, price-protected), and positions are reconciled
  against the chain every `reconcile_sec`.
- **Failure containment**: a rate-limited venue pauses briefly; an
  unreachable venue (e.g. exchange maintenance) pauses trading and is probed
  every `venue_probe_sec` until it recovers; `max_consecutive_errors`
  execution pathologies halt the engine entirely.
- **Live-only**: there is no simulated-fill mode. `--record-only` is the
  risk-free way to run it; anything else trades real money.

## Layout

```
research-workbench/      research CLI, crawler, case studies, and experiments
research-workbench/db/   PostgreSQL migrations, import, backup, and recovery
research-workbench/data/ local evidence, settings, and backups (Git-ignored)
main.py                  entry point (--record-only, or live by default)
entropy_arb/config.py    YAML + .env contract, validation
entropy_arb/book.py      order books + fee-aware crossing/sizing math
entropy_arb/feeds.py     official HL ws + zkLighter ws book feeds
entropy_arb/venue_hl.py  Hyperliquid dex adapter (Entropy, tradexyz)
entropy_arb/venue_lighter.py  zkLighter adapter (mainnet, Robinhood chain)
entropy_arb/engine.py    the two-venue strategy loop
entropy_arb/dashboard.py Rich terminal dashboard
entropy_arb/recorder.py  1-minute orderbook bars
tools/analyze.py         minutes.csv -> suggested thresholds
tests/                   python3 -m pytest tests/
```

## Known risks

- **A wrong midline is a losing strategy.** The premium center drifts;
  re-measure regularly and keep `config.yaml` current.
- **USDG basis** (`lighter-rh`): the hedge quotes in USDG. Part of any
  persistent premium is the stablecoin itself; your midline absorbs the
  level, but a USDG *move* is real PnL.
- **Funding**: two venues, two independent funding rates; carry is not
  modeled. Position caps bound it — keep them modest.
- **Thin books**: Entropy depth can be tiny; `take_fraction` and notional
  caps keep clips small, but slippage on the hedge leg after a partial fill
  is real.
- **Market hours**: for equity perps (e.g. SNDK), off-hours oracle regimes
  differ per venue; consider wider bands or not trading them.
- **One-leg risk**: a leg can fail after the other filled. The bot hedges
  and reconciles automatically, but you should still watch it.

Use at your own risk. This is trading software operating with real money;
nothing here is investment advice. Start with tiny position caps.

## License

[MIT](LICENSE)

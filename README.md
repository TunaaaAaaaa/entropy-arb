# Strategy research workspace

[中文说明](README.zh-CN.md)

A local workspace for collecting evidence, developing hypotheses, and testing independent strategies. Entropy Arbitrage is an archived learning demo; weather and social prediction strategies can be added as peers under `strategies/`.

## Layout

| Location | Responsibility |
|---|---|
| [research-workbench/](research-workbench/README.zh-CN.md) | Shared sources, cases, hypotheses, evidence and research database |
| [strategies/](strategies/README.md) | Independent strategy code, dependencies and experiments |
| [Entropy Arbitrage](strategies/entropy-arbitrage/README.md) | Archived trading-engine demo, excluded from daily research commands |
| [Crypto news bot](strategies/crypto-news-bot/README.md) | V0.2 RSS classification, Feishu / WeCom delivery and independent SQLite history |
| [Architecture and remaining work](ARCHITECTURE.zh-CN.md) | Boundaries, data compatibility and technical debt |

## Local use

Node.js 22+, Python 3.11+ and the workbench dependencies are required. The root package has no runtime dependencies:

```powershell
npm --prefix research-workbench ci
python -m pip install -r research-workbench/requirements-db.txt
npm run db:up
npm run db -- status
npm run workbench -- collect
npm run workbench -- report
npm run db -- records --kind case
npm run db -- export-record case:009
```

These root commands forward to the workbench; its existing commands remain available in `research-workbench/`. Relative file arguments are resolved from the workbench directory. Reports are written to `research-workbench/reports/latest.md`.

A fresh clone has no local database or credentials. Follow the [storage setup and migration guide](research-workbench/POSTGRES-MIGRATION-PLAN.zh-CN.md) before using PostgreSQL; `db:up` only starts an already configured database. Collection checks configured sources; it does not search all X posts or run AI analysis. See [on-demand collection](research-workbench/LOCAL-COLLECTION.zh-CN.md).

## News bot V0.2

From the repository root, install the bot's isolated Python environment, create its local config and run offline acceptance:

```powershell
npm run news:setup
Copy-Item strategies/crypto-news-bot/config.example.yaml strategies/crypto-news-bot/config.yaml
npm run news:smoke
npm run news:once -- --dry-run
```

Set the Feishu webhook in the bot's `config.yaml`. First use `npm run news:verify` to prepare one item, then `npm run news:verify -- --send` to deliver that saved item and verify persistence and deduplication. Use `npm run news:once` for a full collection or `npm run news:start` for scheduled collection. Without any available notifier, candidates are only previewed and never marked as delivered. The bot requires neither Docker nor the workbench database. See its [guide and limitations](strategies/crypto-news-bot/README.md).

WeCom long connections use Bot ID, Secret and the target group's `chat_id` from local YAML. Run `npm run news:wecom` to check authentication, add `-- --discover` to obtain a group ID, or `-- --send-test` to send one test message. See the [WeCom guide](strategies/crypto-news-bot/WECOM.md). Successful deliveries are tracked per destination, so a failed channel doesn't replay a successful one.

## Validation and data

```powershell
npm run test:workbench
npm run test:db
npm run test:demo
npm run test:news
```

Database integration tests require configured PostgreSQL and create isolated test databases. Demo tests additionally need its separate Python dependencies and pytest. No test starts live trading.

The research database and `research-workbench/data/` remain in place. Root `logs/` is retained for historical evidence paths; future demo output belongs to its own directory. Back up PostgreSQL and evidence files together using `npm run db -- backup-pg`. Credentials, collected data and backups are not included in Git. The existing database Compose project name and volume have not changed.

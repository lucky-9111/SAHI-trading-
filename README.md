# SAHI Trading

*Practice. Analyze. Improve.*

A personal **paper-trading** platform (virtual money only). It never places real broker orders.
Independent from the old scanner app.

## Stack
FastAPI · SQLAlchemy 2 · SQLite (PostgreSQL-ready) · Alembic · React + TypeScript + Vite · Tailwind · Lightweight Charts

## Run

Backend:
```
cd backend
python -m venv .venv
.venv\Scripts\pip install --require-hashes --no-deps -r requirements.lock -r requirements-dev.lock
copy .env.example .env      # set SECRET_KEY
.venv\Scripts\uvicorn app.main:app --reload
```
Frontend (new terminal):
```
cd frontend
npm install
npm run dev                 # http://localhost:5173 (proxies /api to :8000)
```
Tests: `cd backend && .venv\Scripts\pytest` (or `-m unit` / `-m integration`), `.venv\Scripts\ruff check .`, and `cd frontend && npm test`.

## Production (AWS EC2) and CI/CD

Merging to `main` runs CI + security checks and deploys automatically to EC2 (release folders, verified database
backup before every deploy, health-gated switch, automatic rollback). Start here:

| Document | For |
|---|---|
| [docs/PRODUCTION_AUDIT.md](docs/PRODUCTION_AUDIT.md) | Architecture, risks found, what was built and why |
| [docs/CI_CD_SETUP.md](docs/CI_CD_SETUP.md) | GitHub secrets, environments, branch protection, updating dependencies |
| [docs/AWS_EC2_SETUP.md](docs/AWS_EC2_SETUP.md) | Preparing the server (and moving the old manual setup) |
| [docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md) | How a deploy works, manual deploy, status, logs, monitoring |
| [docs/ROLLBACK_GUIDE.md](docs/ROLLBACK_GUIDE.md) | Automatic and manual rollback |
| [docs/DATABASE_BACKUP_RESTORE.md](docs/DATABASE_BACKUP_RESTORE.md) | SQLite backups, verification, restore |
| [docs/PRODUCTION_SECURITY.md](docs/PRODUCTION_SECURITY.md) | Secrets, hardening, alerts, HTTPS |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | When something breaks |

## Status

UI follows a light, SAHI-style design (white, black pill buttons, green/red P&L).

| Phase | Scope | State |
|---|---|---|
| 1 | Setup, DB, auth, base UI, dashboard | **Done** |
| 2 | Funds ledger, reset account | Partly done (ledger, deposit, withdraw, multi-portfolio; no reset yet) |
| 3 | Instruments, Angel One market data, charts | **Done** except RSI, Bollinger, drawing tools, live tick feed |
| 4 | Orders, execution engine, order/trade book | **Done** (market/limit, charges estimate, risk checks). No slippage yet |
| 5 | Positions, SL/target, partial exit | **Done**. No trailing SL, no separate Holdings, no 15:20 auto square-off |
| Swing product, Futures, Options | | **Done** (lots, option chain, charges, approximate margin; expiry settlement is approximate; no strategies/spreads) |
| Watchlists, Home (indices, trends, ETFs) | | **Done** (F&O, Commodities, IPO, Research tabs say not available) |
| 6 | Risk management, journal | Not started |
| 7 | Analytics | Not started |
| 8 | Excel export | Not started |
| 9 | Historical replay | Not started |
| 10 | Scanner API integration | Not started |

### Phase 1 delivered
- Register/login (bcrypt, JWT), per-user portfolio authorization.
- Virtual portfolios with an append-only ledger; balance is derived from the ledger (Decimal), overdraw blocked, idempotency key support.
- Dashboard reads from the DB. Trade-derived metrics (P&L, win rate, positions) are zero/empty until trades exist (Phase 4+).
- Collapsible sidebar with all 14 sections; unbuilt ones show an explicit "Not implemented yet" page.
- Alembic wired to the models. Initial migration not generated yet; app uses `create_all` at startup in dev.

### Decisions
- Bearer JWT (simple, works with the Vite proxy). Can move to httpOnly cookies later.
- Balance is never stored, only derived from ledger rows, so it cannot drift.
- Top-bar data status shows DISCONNECTED because no market-data provider is configured (no fake LIVE).

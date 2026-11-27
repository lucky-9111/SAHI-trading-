# Production audit — SAHI Trading

Audit date: 2026-11-27. Scope: the whole repository plus the existing EC2 setup as it was created by hand.
This document records what existed **before** the CI/CD work, the risks found, and the plan that was implemented.

## 1. What the application is

A paper-trading web app (virtual money only). It reads market data from Angel One but **never places broker
orders**: every order goes through the in-house paper engine (`backend/app/trading/engine.py`). There is no call to a
broker order API anywhere in the code.

| Part | Technology (verified in the code) |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy 2, Pydantic Settings, uvicorn; entry point `app.main:app` (`backend/app/main.py`) |
| Frontend | React 19 + TypeScript 7 + Vite 8, Tailwind 3, lightweight-charts 5 (`frontend/`) |
| Database | SQLite, WAL mode (`backend/app/database/session.py`) |
| Auth | Email + password (bcrypt), JWT (HS256, 12 h) sent as a Bearer header; stored in the browser's localStorage |
| Market data | Angel One SmartAPI: REST (quotes, candles) and SmartWebSocketV2 (live ticks); public scrip-master JSON |
| Real-time | Browser WebSocket `/ws/ticks?token=<jwt>` (`backend/app/live/ws.py`) |
| Tests | pytest (117 backend tests at audit time), vitest (13 frontend tests) |

### Background work inside the web process

This is the most important fact for deployment. When the backend starts (`lifespan` in `main.py`) it launches:

1. **Price loop** (`app/trading/poller.py`): a thread that, every 5 s, fills limit orders, triggers stop-loss and
   targets, expires day orders and settles expiring positions.
2. **Live pipeline** (`app/live/pipeline.py`): Angel One websocket receiver thread → tick normaliser → candle builder
   → paper engine on ticks → push to browsers. Daily jobs (intraday square-off) are run from here.
3. **Instrument master sync** when the instruments table is empty.

Consequences:
- The backend must run as **exactly one process with one worker**. Two copies would open two broker websockets and
  evaluate orders twice. (Fills are idempotent at the database level, but the duplicate feed and work is still wrong.)
- During a deployment the old process must be **stopped before** the new one starts. A blue/green or rolling
  deployment (old and new running together) is therefore not safe for this app.
- Pending orders, positions and settings live in the database, so a restart loses no trading state.

### Environment variables (all read by `app/core/config.py` or `os.environ`)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL; SQLite file |
| `SECRET_KEY` | JWT signing key |
| `CORS_ORIGINS` | Allowed browser origins |
| `ACCESS_TOKEN_MINUTES`, `DEFAULT_CAPITAL`, `PAPER_SLIPPAGE_PCT`, `INTRADAY_SQUAREOFF_MINUTES_BEFORE_CLOSE` | App behaviour |
| `FEED_MODE` | `live` / `replay` / `off` |
| `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PASSWORD`, `ANGEL_TOTP_SECRET` | Broker market-data login |
| `DISABLE_AUTO_SYNC`, `DISABLE_ENGINE`, `FEED_MAX_TOKENS`, `FEED_STALL_SECONDS`, `RECORD_TICKS`, `REPLAY_FILE`, `REPLAY_SPEED` | Tests / tooling |
| *(added by this work)* `ENVIRONMENT`, `TRUSTED_HOSTS` | Production guard, Host-header allow-list |

### Database schema management

- At startup the app runs `Base.metadata.create_all()` (creates **missing** tables, never drops or alters) and
  `ensure_columns()` (adds a fixed list of new columns with `ALTER TABLE ADD COLUMN`). Both are additive only.
- Alembic is configured but has a single initial migration and is **not in sync** with the models (later tables such
  as `live_candles`, `trade_log`, `market_calendar` were created by `create_all`). Running `alembic upgrade head` on
  production would fail or do the wrong thing. **Decision: deployments do not run Alembic.** Schema changes stay
  additive, and a verified backup is taken before every new release starts.

## 2. How production looked before this work

| Item | State | Risk |
|---|---|---|
| Deployment | Manual: `git archive` + `scp` + extract over `/opt/sahi` + restart | No checks, no history, no rollback, files overwritten in place |
| Service | systemd `sahi`, user `ubuntu` (has sudo), `uvicorn` default options | App ran as an admin user; no hardening |
| Code + data location | `/opt/sahi/backend` holds the code **and** `agroup_trader.db` (relative path) **and** `.env` | A deploy that cleans the folder deletes the database |
| Dependencies | `requirements.txt` with `>=` ranges, no lock, test tools mixed in | A rebuild can silently pull different (or compromised) versions |
| Secrets | `/opt/sahi/backend/.env`, permissions not managed | Readable by anything running as ubuntu |
| Nginx | Basic proxy; `/health` (feed internals, queue sizes) public; no security headers; default timeouts; no size limit | Information exposure, no XSS/clickjacking headers, no brute-force limit on login |
| Backups | None | One disk failure or bad command loses all user data |
| Monitoring | None beyond `systemctl status` | Outages unnoticed |
| CI | None | Broken code can reach production |
| API docs | `/docs` and `/openapi.json` reachable in production | Full API surface published |
| Production guard | Default `SECRET_KEY = "CHANGE_ME_IN_ENV"` would be accepted | Forgeable login tokens if the env file is incomplete |
| Host header | Any Host accepted | Host-header attacks / cache poisoning |
| Line endings | Git `core.autocrlf=true` on the developer PC | Shell scripts copied from Windows would break on Linux |

Things that were already right: the frontend contains no secrets (Angel keys stay on the server), passwords are
bcrypt-hashed, every API route checks account ownership, the backend listens on 127.0.0.1 only, WAL mode is on, and
trading state survives restarts.

## 3. Target architecture (implemented)

```
GitHub (main) ──push──▶ Actions: CI + Security ──▶ package sahi-<sha>.tar.gz ──scp/ssh (deploy key)──▶ EC2
                                                                                                   │
  /opt/sahi/releases/<time>-<sha>/  backend/ frontend/dist/ venv/ deploy/ REVISION   (read-only, root)│
  /opt/sahi/current ──symlink──▶ the live release                                                    │
  /var/lib/sahi/sahi.db           database (never inside a release, never touched by deploys)       │
  /etc/sahi/sahi.env              secrets (root:sahi 0640)                                           │
  /var/backups/sahi/              verified, compressed backups                                       │
                                                                                                     ▼
  internet ──:80──▶ nginx (static SPA, /api, /ws) ──127.0.0.1:8000──▶ uvicorn (1 worker, user sahi)
```

Deployment flow (`deploy/bin/sahi-deploy`): stage + checksum → hash-pinned venv → **smoke boot on a temp DB** →
**verified DB backup** → stop old → switch symlink → nginx `-t` → start new → **health gate** → done, or
**automatic rollback** to the previous good release.

### Honest limitation: downtime

Zero-downtime is **not** achieved and is not claimed. Because the backend owns the broker feed and the price loop,
old and new must not overlap, so the API is unavailable from "stop old" until "new is ready": about **5–15 seconds**
per deploy (measured 13 s in rehearsal, including a 10 s stability check that runs while the new version is already
serving). Static pages keep being served by nginx throughout; the browser websocket reconnects automatically
(`frontend/src/utils/liveSocket.ts` falls back to REST while disconnected). Real zero-downtime would need the feed and
price loop moved into a separate worker process plus a database that supports concurrent writers (PostgreSQL).

## 4. Implementation plan (all done)

| Phase | What | Where |
|---|---|---|
| 1 | Audit | this file |
| 2 | CI: lint, unit/integration tests, boot test, frontend type-check/tests/build, config checks | `.github/workflows/ci.yml` |
| 3 | Security: gitleaks, repo hygiene, pip-audit, npm audit, CodeQL, workflow lint, Dependabot | `.github/workflows/security.yml`, `codeql.yml`, `.github/dependabot.yml`, `deploy/ci/` |
| 4 | Production config: `ENVIRONMENT`, startup refusal on unsafe settings, trusted hosts, docs off, env templates | `backend/app/core/config.py`, `backend/app/main.py`, `deploy/server/sahi.env.example`, `backend/.env.example` |
| 5–6 | CD + systemd: release tarball, SSH deploy with pinned host key, hardened single-worker service | `.github/workflows/deploy.yml`, `deploy/bin/sahi-deploy`, `deploy/systemd/` |
| 7 | Nginx: SPA, API, WebSocket, headers, CSP, limits, rate limit, internal-only diagnostics | `deploy/nginx/sahi.conf` |
| 8 | SQLite safety: data outside releases, verified backups, daily timer, retention, restore | `deploy/bin/sahi-backup`, `sahi-restore`, `sahi_sqlite.py` |
| 9–10 | Release directories, health gate, automatic + manual rollback | `deploy/bin/sahi-deploy`, `sahi-rollback`, `sahi-common.sh` |
| 11 | Health endpoints, monitor timer, status command | `/api/health/live`, `/api/health/ready`, `deploy/bin/sahi-monitor`, `sahi-status` |
| 12 | Trading safety: single instance, stop-before-start, smoke boot with feed/engine off and no broker keys | service unit, `smoke-boot.sh` |
| 13 | Release management: main-only deploys, concurrency lock, deploy tags, history log | `deploy.yml`, `/var/log/sahi/deploy-history.log` |
| 14 | Documentation | `docs/*.md` |

No trading logic, indicators, strategy code or order execution code was changed.

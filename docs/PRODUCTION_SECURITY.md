# Production security

## Where secrets live

| Secret | Location | Never in |
|---|---|---|
| Angel One API key / client code / password / TOTP secret | `/etc/sahi/sahi.env` on the server (`root:sahi`, 0640) | Git, GitHub, frontend, logs |
| `SECRET_KEY` (JWT signing) | same file | same |
| CI deploy SSH private key | GitHub environment secret `EC2_SSH_KEY` | the server, Git |
| EC2 admin key (`.pem`) | your PC only | GitHub, the server |
| Server host key fingerprint | GitHub secret `EC2_SSH_KNOWN_HOSTS` (public data, stored as a secret for integrity) | — |

- `.env`, `*.db`, `*.pem`, `*.key`, credential JSON files are in `.gitignore`, rejected by the security workflow if
  ever tracked, and rejected again by `build-release.sh` and `sahi-deploy` if they appear in a release.
- The frontend bundle is scanned in CI for server-side secret names.
- Health endpoints return only `ok` / `unavailable`; feed diagnostics are reachable only from the server itself.
- Scripts print variable **names**, never values. GitHub masks secret values in logs.

## Application settings enforced in production

With `ENVIRONMENT=production` the backend **refuses to start** (and the deploy rolls back) if:
- `SECRET_KEY` is a known default or shorter than 32 characters
- `CORS_ORIGINS` is empty or contains `*`
- `TRUSTED_HOSTS` is `*` (Host header allow-list; `localhost` and `127.0.0.1` are always added for health checks)
- `DATABASE_URL` is a relative SQLite path

Also in production: `/docs`, `/redoc` and `/openapi.json` are disabled; requests with an unknown `Host` header get
HTTP 400. FastAPI debug mode is never enabled. CORS lists only the site's own origin (the frontend is served from the
same origin, so CORS is not needed for normal use at all).

Cookies: the app does not use cookies. The login token is a Bearer JWT kept in the browser's `localStorage`, so the
main risk is XSS. It is mitigated by React's escaping and a strict Content-Security-Policy (`script-src 'self'`, no
inline scripts, no third-party scripts). Verified in a headless browser: zero CSP violations on every page. Moving the
token to an `HttpOnly; Secure; SameSite=Strict` cookie is a possible future change once HTTPS exists.

## Server hardening in place

- Backend runs as user `sahi` (no shell, no sudo) under a hardened systemd unit: read-only system
  (`ProtectSystem=strict`), only `/var/lib/sahi` writable, no new privileges, private `/tmp`, no capabilities,
  restricted address families.
- Backend listens on `127.0.0.1:8000` only; uvicorn trusts proxy headers from 127.0.0.1 only.
- CI logs in as `deploy` with a dedicated key (no password; `no-pty`, no forwarding) and may run only three
  root-owned scripts through sudo; each validates its arguments (40-hex commit, 64-hex checksum, tarball inside
  `/home/deploy/incoming`). The server's host key is pinned, so CI cannot be tricked into deploying to another machine.
- Release tarballs are checksum-verified, path-checked and owned by root after staging; Python packages are
  installed only from the hash-pinned lock, wheels only (no build scripts run).
- nginx: `server_tokens off`, CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`,
  `Cross-Origin-Opener-Policy`, 1 MB body limit, timeouts, hidden files denied, **login/register rate limit**
  (10/min per IP, burst 5 → HTTP 429).
- Journald capped at 500 MB; SmartAPI log folders deleted after 30 days.

Recommended extra steps (manual): SSH hardening + `unattended-upgrades` + `fail2ban`
([AWS_EC2_SETUP.md](AWS_EC2_SETUP.md#ssh-hardening-recommended-on-any-server)), Elastic IP, EBS snapshots, off-server
backups, and closing port 22 to the internet with the optional OIDC setup in [CI_CD_SETUP.md](CI_CD_SETUP.md).

## GitHub Actions least privilege

- Every workflow starts with `permissions: contents: read`. Only the deploy job adds `contents: write` (to push the
  `deploy-*` tag) and `id-token: write` (only used for the optional AWS step); CodeQL adds `security-events: write`.
- All third-party actions are pinned to full commit SHAs (checked by `deploy/ci/check-workflows.py`), and were
  chosen from releases at least two weeks old. Dependabot proposes updates as pull requests.
- No `pull_request_target`; pull requests from forks get no secrets.
- `persist-credentials: false` on checkouts that do not push.
- Deploys only from `main`, through the `production` environment (restrict it to `main`; optionally require approval).

## Handling security alerts

| Alert | Where | What to do |
|---|---|---|
| **gitleaks / repo hygiene** finds a secret | Security workflow fails | Treat the secret as compromised: **rotate it first** (new Angel One API key/password, new `SECRET_KEY`, new deploy key), then remove the file (`git rm --cached`), and if it is in history, rewrite history (`git filter-repo`) and force-push with the maintainer's agreement. Removing it from the latest commit alone is not enough. |
| **pip-audit** vulnerability | Security workflow fails (blocks deploys) | Check whether the vulnerable code path is used. Upgrade the package in the lock ([CI_CD_SETUP.md → Updating dependencies](CI_CD_SETUP.md#updating-dependencies)) in a PR; CI must pass. If no fix exists and the code path is unused, document it and add `--ignore-vuln <ID>` to the audit command in `security.yml` with a comment and a review date. |
| **npm audit** high/critical | Security workflow fails | Same: `npm install <pkg>@<fixed>` or accept the Dependabot PR; build-tool-only issues fail at critical level only. |
| **CodeQL** finding | Security → Code scanning | Review; fix in a PR, or dismiss with a reason if it is a false positive. |
| **Dependabot** PR | Pull requests | Let CI run; read the changelog for major versions; merge manually. |

Nothing is upgraded or deployed automatically because of an alert.

Private repositories: CodeQL needs GitHub Code Security (paid) on private repos; without it the CodeQL workflow
fails. Either enable it, make the repo public, or delete `.github/workflows/codeql.yml`. It is not a deploy gate.

## HTTPS (when a domain is connected)

Browsers only trust certificates for domain names, so HTTPS is set up once a domain exists. Do **not** use a
self-signed certificate for the bare IP.

1. Point the domain's `A` record to the Elastic IP.
2. On the server:
   ```bash
   sudo apt-get install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d trade.example.com --redirect -m you@example.com --agree-tos
   ```
   Certbot adds a `listen 443 ssl` block and an HTTP→HTTPS redirect, and renews automatically
   (`systemctl list-timers | grep certbot`).
3. Update `/etc/sahi/sahi.env`:
   `CORS_ORIGINS=https://trade.example.com` and `TRUSTED_HOSTS=trade.example.com`, then
   `sudo systemctl restart sahi-backend`.
4. Make it permanent in the repository: copy the certbot-generated `server` blocks into `deploy/nginx/sahi.conf`
   (otherwise the next deploy reinstalls the HTTP-only file), add
   `add_header Strict-Transport-Security "max-age=31536000" always;`, change the CSP's `connect-src` to
   `'self' wss://trade.example.com`, and update the `EC2_HOST` secret to the domain. Open port 443 in the security group.

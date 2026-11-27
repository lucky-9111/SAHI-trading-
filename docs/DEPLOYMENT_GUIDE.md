# Deployment guide

## Automatic deployment (normal way)

Merge a pull request into `main`. The **Deploy** workflow runs CI and the security checks again on the merged
commit, packages it, and installs it on the server. Watch it under GitHub → **Actions → Deploy**.

What happens on the server (`sahi-deploy`), in order:

| Step | What | If it fails |
|---|---|---|
| 1 | Lock (one deploy at a time), check arguments, disk space (>1 GB), database present, legacy service gone | Stops; nothing changed |
| 2 | Copy the tarball, check its SHA-256, refuse unsafe paths, check `REVISION` equals the commit, refuse `.env`/`.db`/`.pem` files | Stops; nothing changed |
| 3 | New virtualenv from the hash-pinned lock (wheels only), `pip check`, byte-compile | Stops; nothing changed |
| 4 | **Smoke boot** of the new code on a temporary database, broker feed off, price loop off, no broker keys | Stops; nothing changed |
| 5 | **Verified backup** of the live database (`pre-deploy-<release>`) | Stops; nothing changed |
| 6 | Stop the backend gracefully (finishes requests, closes the feed) | Rollback |
| 7 | Point `/opt/sahi/current` at the new release (atomic symlink switch) | Rollback |
| 8 | Install the release's nginx site if it changed, `nginx -t`, reload | Old nginx file restored, rollback |
| 9 | Start the backend | Rollback |
| 10 | **Health gate**: readiness (DB query) within 90 s, no crash loop, service active, nginx valid, SPA + JS asset + API through nginx, still healthy after 10 s | Rollback |
| 11 | Mark release good, record history, delete old releases (keeps 5 + current + previous good) | — |

Then GitHub checks `http://<EC2_HOST>/` from outside and tags the commit `deploy-<time>-<sha>`.

**Downtime:** the API is unavailable between step 6 and step 10 passing, about 5–15 seconds. This is deliberate:
the old and new backend must never run together, because each one runs the broker feed and the order price loop.
nginx keeps serving the web pages meanwhile, and the app's live prices reconnect automatically.

**Database:** never replaced or reset by a deploy. On start, the app only *adds* missing tables/columns
(`create_all` + `ensure_columns`); Alembic is not run (see [PRODUCTION_AUDIT.md](PRODUCTION_AUDIT.md)).

## Manual deployment (without GitHub Actions)

Use this if GitHub is unavailable. Run on your PC from a clean checkout of the commit you want (Git Bash or Linux):

```bash
cd frontend && npm ci && npm run build && cd ..
bash deploy/build-release.sh out
SHA=$(git rev-parse HEAD)
SUM=$(cut -d' ' -f1 out/sahi-$SHA.tar.gz.sha256)
scp -i <your-key.pem> out/sahi-$SHA.tar.gz ubuntu@<EC2_PUBLIC_IP>:/tmp/
ssh -i <your-key.pem> ubuntu@<EC2_PUBLIC_IP> \
  "sudo install -o deploy -g deploy -m 0640 /tmp/sahi-$SHA.tar.gz /home/deploy/incoming/ && \
   sudo sahi-deploy /home/deploy/incoming/sahi-$SHA.tar.gz $SHA $SUM"
```

`build-release.sh` refuses to package if tracked files have uncommitted changes, so the tarball always equals a
real commit.

## Checking status

```bash
sudo sahi-status                          # release, services, health, last deploys, latest backups
cat /opt/sahi/DEPLOYED_REVISION           # commit that is live
column -t -s $'\t' /var/log/sahi/deploy-history.log | tail
sudo sahi-rollback --list                 # all releases: good / FAILED / current (*)
curl -s http://127.0.0.1/api/health/ready # {"status":"ok"}
```

## Restarting services

```bash
sudo systemctl restart sahi-backend       # backend (5–10 s API downtime; pending orders stay in the DB)
sudo systemctl reload nginx               # after editing nginx config (always run `sudo nginx -t` first)
sudo systemctl status sahi-backend        # state + last log lines
```

Changing a runtime setting (e.g. Angel One password): `sudo nano /etc/sahi/sahi.env`, then
`sudo systemctl restart sahi-backend`.

## Logs

```bash
journalctl -u sahi-backend -f                     # backend, live
journalctl -u sahi-backend --since "1 hour ago"   # backend, recent
journalctl -u sahi-backend -p err --since today   # errors only
sudo tail -f /var/log/nginx/access.log            # every HTTP request
sudo tail -f /var/log/nginx/error.log             # nginx problems (502 = backend down)
journalctl -t sahi-monitor --since today          # monitor findings
journalctl -u sahi-backup --since "2 days ago"    # backup runs
sudo ls /var/lib/sahi/logs/                       # SmartAPI library error logs (kept 30 days)
```

The live pipeline writes one JSON object per line (`"stage"`, `"token"`, `"symbol"` fields), so
`journalctl -u sahi-backend -o cat | grep '"stage"'` shows only feed events. Journald is capped at 500 MB.

## Monitoring

`sahi-monitor.timer` runs every 5 minutes and checks: backend active + ready, nginx active, frontend served, disk
(< 85 % on `/`, data and backup folders), memory (> 10 % available), CPU load, newest backup younger than 26 h.
Problems are written to the journal with priority `err` (`journalctl -t sahi-monitor -p err`).

For phone/Slack alerts put a webhook URL into `/etc/sahi/monitor.env`:
```bash
echo 'ALERT_WEBHOOK_URL=https://hooks.slack.com/services/...' | sudo tee /etc/sahi/monitor.env >/dev/null
```
It posts `{"text": "..."}` once when a check starts failing and once when it recovers (works with Slack, Mattermost,
Discord's `/slack` webhook URLs, and most chat tools). Outside monitoring (e.g. an UptimeRobot HTTP check on
`http://<EC2_PUBLIC_IP>/api/health/ready`) is recommended, because a dead server cannot report on itself.

## Health endpoints

| URL | Public | Answers |
|---|---|---|
| `/api/health/live` | yes | `{"status":"ok"}` if the process answers |
| `/api/health/ready` | yes | `{"status":"ok"}` if the database answers, else HTTP 503 `{"status":"unavailable"}` |
| `/api/health` | yes | app name, paper-trading flag |
| `/api/live/health`, `/health` | **server only** (nginx denies others) | feed state, tick ages, queue sizes |

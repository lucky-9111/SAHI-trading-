# Troubleshooting

Start with `sudo sahi-status`; it shows the live release, service states, health codes, recent deploys and backups.

## The site does not load

| Symptom | Check | Fix |
|---|---|---|
| Browser cannot connect at all | Instance running? Security group allows port 80? `systemctl is-active nginx` | Start instance / fix SG / `sudo systemctl start nginx` |
| **502 Bad Gateway** | `systemctl status sahi-backend`, `journalctl -u sahi-backend -n 100` | See "Backend will not start" |
| **400 Bad Request** on every page | The address you typed is not in `TRUSTED_HOSTS` (e.g. the public IP changed) | Update `TRUSTED_HOSTS` and `CORS_ORIGINS` in `/etc/sahi/sahi.env`, restart backend |
| White page | Browser console (F12). `curl -s http://127.0.0.1/ | head` on the server | Hard-reload (Ctrl+F5); if index.html is wrong, `sudo sahi-rollback` |
| **429 Too Many Requests** on login | Login rate limit (10/min per IP) | Wait one minute |
| Prices not live | `curl -s http://127.0.0.1/api/live/health` on the server | See "Market data" |

## Backend will not start

```bash
journalctl -u sahi-backend -n 100 --no-pager
```

| Log line | Cause | Fix |
|---|---|---|
| `Refusing to start in production: SECRET_KEY ...` (or CORS / TRUSTED_HOSTS / DATABASE_URL) | Unsafe setting in `/etc/sahi/sahi.env` | Fix the named variable, `sudo systemctl restart sahi-backend` |
| `unable to open database file` / `readonly database` | Permissions | `sudo chown sahi:sahi /var/lib/sahi /var/lib/sahi/sahi.db*` and `sudo chmod 750 /var/lib/sahi` |
| `database disk image is malformed` | Corruption | Stop the backend; restore the newest good backup ([DATABASE_BACKUP_RESTORE.md](DATABASE_BACKUP_RESTORE.md)) |
| `No space left on device` | Disk full | `df -h`; `sudo journalctl --vacuum-size=200M`; delete old backups you no longer need; grow the EBS volume |
| `Address already in use` (port 8000) | Old legacy service still running | `sudo systemctl disable --now sahi` |
| `ModuleNotFoundError` | Broken release | `sudo sahi-rollback` |
| `start request repeated too quickly` | systemd gave up after 10 crashes in 5 min | Fix the cause, then `sudo systemctl reset-failed sahi-backend && sudo systemctl start sahi-backend` |

## Deploy workflow failed

Open the failed step in GitHub Actions.

| Step / message | Meaning | Fix |
|---|---|---|
| `Check required secrets` | A GitHub secret is missing | Add it under Settings → Environments → production |
| `Host key verification failed` | Server host key differs from `EC2_SSH_KNOWN_HOSTS` | If you rebuilt the server: re-run `ssh-keyscan`, **verify the fingerprint on the server**, update the secret. If not: someone may be intercepting — do not bypass. |
| `Permission denied (publickey)` | Deploy key not installed on the server | Re-run bootstrap with `--deploy-key "<public key>"` |
| `Connection timed out` | Port 22 closed for GitHub | Security group, or set up the optional OIDC rule ([CI_CD_SETUP.md](CI_CD_SETUP.md)) |
| `sudo: a password is required` / `not allowed` | sudoers rule missing | Re-run bootstrap |
| `legacy 'sahi' service is still running` | Migration not done | `sudo sahi-migrate-legacy` ([AWS_EC2_SETUP.md](AWS_EC2_SETUP.md)) |
| `database ... not found. Refusing to start on an empty database` | `/var/lib/sahi/sahi.db` missing | If data should exist: find out why before anything else (restore from backup). Only for a genuinely new install: `sudo touch /var/lib/sahi/.allow-empty-db` |
| `another deploy / rollback / restore is running` | Lock held | Wait; if nothing is running (crashed shell): the lock clears automatically when that process ends |
| `checksum mismatch` | Upload corrupted or tampered | Re-run the workflow |
| `dependency installation failed` | PyPI unreachable or no wheel for the server's Python | Check `curl -I https://pypi.org` on the server; re-run |
| `smoke boot failed` | New code cannot boot in production mode | Fix in code (the output shows the server log). Live site untouched. |
| `pre-deploy database backup failed` | Disk space or database problem | `df -h`; `sudo sahi-backup manual` to see the error. Live site untouched. |
| `FAILED; rolled back to ... (healthy)` | New release failed the health gate | Read the `journal:` lines in the step log, fix, merge again |
| `rollback ... is ALSO unhealthy` | Server-level problem | Follow "Backend will not start" |
| `Public health check` failed but install succeeded | Server is fine locally; outside access broken | Security group / Elastic IP / `EC2_HOST` value |

## Market data

`curl -s http://127.0.0.1/api/live/health` → `feed.state`:
- `connected` — fine. `stale` — no ticks recently (normal outside market hours). `reconnecting` — Angel One
  dropped the connection; the receiver retries with backoff. `closed` — no live feed (check `FEED_MODE` and keys).
- `Angel One credentials are not set` in the app: add the four `ANGEL_*` values to `/etc/sahi/sahi.env` and restart.
  (The message mentions `backend/.env`; on the server the file is `/etc/sahi/sahi.env`.)
- Login errors from Angel One: the TOTP secret or password changed. Update the env file and restart.

## Restarting everything safely

```bash
sudo systemctl restart sahi-backend
sudo nginx -t && sudo systemctl reload nginx
sudo sahi-status
```
Restarts do not lose trading state: pending orders, positions and SL/targets are in the database and are picked up
again by the price loop. Orders are never sent to a broker (paper trading), so a restart cannot duplicate real orders.

## The server is lost or will not boot

1. **Don't panic about data** if you have off-server backups (S3) or EBS snapshots.
2. Launch a new Ubuntu instance (or restore the latest EBS snapshot as a new volume/instance and skip to step 6).
3. Follow [AWS_EC2_SETUP.md → B. Brand-new server](AWS_EC2_SETUP.md#b-brand-new-server), but **do not** create
   `.allow-empty-db`.
4. Put the database back before the first deploy:
   ```bash
   aws s3 cp s3://<bucket>/sahi/<newest>.db.gz /tmp/   # or scp it from your PC
   gunzip -c /tmp/<newest>.db.gz | sudo tee /var/lib/sahi/sahi.db >/dev/null
   sudo chown sahi:sahi /var/lib/sahi/sahi.db && sudo chmod 640 /var/lib/sahi/sahi.db
   python3 -I /usr/local/lib/sahi/sahi_sqlite.py verify /var/lib/sahi/sahi.db
   ```
5. Restore `/etc/sahi/sahi.env` values: Angel One keys from your Angel account, and the old `SECRET_KEY` if you kept
   it (otherwise users just log in again).
6. Update GitHub secrets `EC2_HOST` (if the IP changed) and `EC2_SSH_KNOWN_HOSTS` (new host key — verify it), then
   run Actions → Deploy → Run workflow.
7. Move the Elastic IP to the new instance so users keep the same address.

## Useful one-liners

```bash
sudo sahi-rollback --list                                   # releases
column -t -s $'\t' /var/log/sahi/deploy-history.log | tail  # deploy history
ls -lt /var/backups/sahi | head                             # backups
systemctl list-timers | grep sahi                           # next backup / monitor run
journalctl -t sahi-monitor -p warning --since today         # monitor problems
sudo -u sahi sqlite3 /var/lib/sahi/sahi.db 'PRAGMA integrity_check'   # needs: sudo apt install sqlite3
```

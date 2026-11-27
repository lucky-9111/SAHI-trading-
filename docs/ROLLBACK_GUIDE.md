# Rollback guide

Rollback switches the **application code** back to an earlier release. It never changes the database.

## Automatic rollback (during a deploy)

`sahi-deploy` rolls back by itself when the new release fails after the old one was stopped:

- nginx configuration of the new release fails `nginx -t`
- backend does not become ready within 90 s, or crash-loops (2 automatic restarts)
- service not active, or restarted during the 10 s stability window
- frontend `index.html`, a JS asset, or the API is not served through nginx

What it does: marks the release `.failed` → prints the last 40 backend log lines → stops the backend → puts the old
nginx site back → points `current` at the previous **good** release → starts it → runs the same health gate. The
GitHub job is always marked **failed**, with one of these messages:

| Message | Meaning |
|---|---|
| `FAILED; rolled back to <release> (healthy)` | Site is up on the previous version. Fix the code, merge again. |
| `no previous good release; service left stopped` | First-ever deploy failed. Fix and deploy again. |
| `rollback ... is ALSO unhealthy - manual action required` | Usually a server problem (disk full, env file, database). See [TROUBLESHOOTING.md](TROUBLESHOOTING.md). |

Failures **before** the switch (checksum, dependencies, smoke boot, backup) never stop the live site at all.

Tested in a rehearsal on Ubuntu 26.04 + systemd: invalid nginx config, broken frontend, and a backend that crashes
only in production were each rolled back automatically, with the previous release healthy afterwards.

## Manual rollback

```bash
sudo sahi-rollback --list          # * = live; good / FAILED / staged
sudo sahi-rollback                 # to the newest good release before the current one
sudo sahi-rollback 20261127093000-0123456789ab   # to a specific good release
```

Only releases that passed the health gate before (`good`) are accepted. The same health gate runs afterwards. The
`deploy` user can run it too (`sudo -n /usr/local/sbin/sahi-rollback`), so it can also be scripted from CI.

Important: after a manual rollback, the next merge to `main` deploys `main` again. If `main` is still broken,
revert the bad commit on GitHub (open the PR → **Revert**) so the pipeline deploys the fixed state.

## Why the database is not rolled back

Restoring a backup throws away every order, fill and deposit made since that backup. That is a business decision,
never an automatic one. Code rollback is safe without it because schema changes are additive (new tables/columns are
simply ignored by older code). If data really must go back, follow
[DATABASE_BACKUP_RESTORE.md](DATABASE_BACKUP_RESTORE.md) — every deploy leaves a `pre-deploy-<release>` backup.

## Rollback when the server itself is broken

See [TROUBLESHOOTING.md → server lost](TROUBLESHOOTING.md#the-server-is-lost-or-will-not-boot).

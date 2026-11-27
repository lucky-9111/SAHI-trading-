# SQLite backup and restore

Database file: `/var/lib/sahi/sahi.db` (plus `sahi.db-wal` / `sahi.db-shm` while the app runs, because it uses
WAL mode). Owner `sahi`, mode 0640, outside every release folder.

**Never copy the `.db` file with `cp` while the app runs** — a copy taken mid-write can be corrupt, and without the
`-wal` file it misses recent writes. Always use `sahi-backup`, which uses SQLite's own backup API.

## Why WAL is fine here

WAL mode was already enabled by the app. It is safe because exactly one process (the single uvicorn worker) writes
to the database; SQLite serialises writes from its threads. Backups read a consistent snapshot without blocking the
app. Do not run a second copy of the backend, and do not put the database on a network filesystem.

## Automatic backups

| When | Tag | Kept |
|---|---|---|
| Daily 02:30 IST (`sahi-backup.timer`; catches up after downtime) | `daily` | 14 days |
| Before every deploy | `pre-deploy-<release>` | newest 10 |
| Before every restore | `pre-restore-<time>` | until you delete them |
| Legacy migration | `legacy-migration` | until you delete it |

Each backup: SQLite online backup → `PRAGMA integrity_check` must be `ok` → core tables (`users`, `trading_accounts`,
`virtual_funds_ledger`, `orders`, `positions`, `trades`) must exist → gzip → `gzip -t` → SHA-256 file. Files:
`/var/backups/sahi/sahi-<UTC time>-<tag>.db.gz` and `.db.gz.sha256`. If any check fails, the backup is discarded and
the run fails (visible in `journalctl -u sahi-backup` and flagged by the monitor after 26 h without a backup).

Retention can be changed in `/etc/sahi/backup.env`:
```bash
BACKUP_RETENTION_DAYS=30
BACKUP_KEEP_PREDEPLOY=20
```

## Manual backup

```bash
sudo sahi-backup manual             # or any tag: sudo sahi-backup before-big-change
ls -lt /var/backups/sahi | head
```

## Off-server copies (strongly recommended)

Backups on the same disk do not survive losing the instance. Either:

- **S3**: create a private bucket (versioning on, lifecycle rule to expire after e.g. 90 days), give the instance an
  IAM role allowing `s3:PutObject` on `arn:aws:s3:::<bucket>/sahi/*`, install the AWS CLI
  (`sudo snap install aws-cli --classic`), then:
  ```bash
  echo 'BACKUP_S3_URI=s3://<bucket>/sahi' | sudo tee -a /etc/sahi/backup.env
  sudo sahi-backup manual           # check it reports "copied to off-server storage"
  ```
- and/or **EBS snapshots** of the volume (AWS Backup, daily).

Download one to your PC occasionally: `scp -i <your-key.pem> ubuntu@<EC2_PUBLIC_IP>:/var/backups/sahi/<file>.db.gz .`
(as ubuntu you may first need `sudo cp` it to /tmp and `sudo chown ubuntu`).

## Verify a backup without restoring

```bash
f=/var/backups/sahi/sahi-20261127T210300Z-daily.db.gz
(cd /var/backups/sahi && sha256sum -c "$(basename $f).sha256")
gunzip -c "$f" > /tmp/check.db
python3 -I /usr/local/lib/sahi/sahi_sqlite.py verify /tmp/check.db   # {"ok": true, ...}
python3 -I /usr/local/lib/sahi/sahi_sqlite.py counts /tmp/check.db   # rows per table
rm /tmp/check.db
```

## Restore (emergency)

Everything written after the chosen backup is lost (it remains in the automatic `pre-restore` backup).

```bash
ls -lt /var/backups/sahi/*.db.gz | head                 # pick the backup
sudo sahi-restore /var/backups/sahi/<file>.db.gz --yes
```

`sahi-restore`:
1. checks the SHA-256, `gzip -t`, integrity and core tables of the backup — **before** stopping anything;
2. stops the backend and pauses the backup timer;
3. backs up the current database as `pre-restore-<time>` (or, if it is too damaged for that, copies the raw
   `.db`/`-wal`/`-shm` files into `/var/backups/sahi/pre-restore-raw-<time>/`);
4. installs the restored file and deletes the old `-wal`/`-shm` (an old WAL must never be applied to another file);
5. starts the backend and waits until it is ready.

Tested in rehearsal: a corrupted backup is refused with the live service untouched; a valid restore brings the
database back to the backup's state.

Restoring from S3: `aws s3 cp s3://<bucket>/sahi/<file>.db.gz /var/backups/sahi/` (and the `.sha256`), then
`sudo chown sahi:sahi /var/backups/sahi/<file>*` and run `sahi-restore` as above.

## Schema changes and migrations

- The app adds missing tables/columns at startup; it never drops or rewrites data. A verified backup is taken before
  every new release starts, so even an additive change has a restore point.
- Do **not** run `alembic upgrade` on production: the migration history is not in sync with the models.
- A change that is *not* additive (renaming/dropping a column, changing types, moving data) needs a written plan:
  manual backup → run the change in a maintenance window → verify → keep the backup. Never put such a change in the
  automatic startup code.

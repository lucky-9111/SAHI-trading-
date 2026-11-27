# AWS EC2 setup

Prepares an Ubuntu Server LTS instance (tested on Ubuntu 26.04 with Python 3.14 and sudo-rs) for automatic
deployments. Two paths: **A** moves the existing hand-made installation over (keeps all users and trades);
**B** is a brand-new server.

Commands marked *(PC)* run on your computer (PowerShell or Git Bash); everything else runs on the server
after `ssh -i <your-key.pem> ubuntu@<EC2_PUBLIC_IP>`.

## Users and folders this creates

| Name | What it is |
|---|---|
| user `sahi` | Runs the backend. No login, no sudo. Owns only `/var/lib/sahi` and `/var/backups/sahi`. |
| user `deploy` | Used by GitHub Actions over SSH. Key-only login, no password. Through sudo it can run **only** `sahi-deploy`, `sahi-rollback`, `sahi-status`. |
| `/opt/sahi/releases/` | One folder per deployed version (read-only, owned by root) |
| `/opt/sahi/current` | Symlink to the live release |
| `/var/lib/sahi/sahi.db` | The database. Never inside a release; deploys never touch it. |
| `/etc/sahi/sahi.env` | Runtime secrets (`root:sahi`, mode 0640) |
| `/var/backups/sahi/` | Verified database backups |
| `/var/log/sahi/deploy-history.log` | Every deploy / rollback with time and commit |
| `/usr/local/sbin/sahi-*` | Ops commands (installed by bootstrap, root-owned) |

## Security group (AWS console → EC2 → Security groups)

| Port | Source | Why |
|---|---|---|
| 80/tcp | 0.0.0.0/0 (and ::/0) | The website |
| 22/tcp | **Your IP** only, plus either `0.0.0.0/0` for GitHub Actions or the optional temporary-rule setup in [CI_CD_SETUP.md](CI_CD_SETUP.md#5-optional-keep-ssh-closed-to-the-internet) | SSH |
| 8000 | **not open** | The backend listens on 127.0.0.1 only |

Also recommended: attach an **Elastic IP** (a stopped/started instance otherwise gets a new public IP, and the
`EC2_HOST` secret, `TRUSTED_HOSTS` and `CORS_ORIGINS` would all have to change), and enable EBS snapshots
(AWS Backup or Data Lifecycle Manager, daily) as a second safety net for the disk.

## A. Move the existing installation (one time)

The current server runs a `sahi` service as `ubuntu` from `/opt/sahi/backend` with the database inside the code
folder. These steps keep every user, order and position.

**1. Copy the deploy folder to the server** *(PC, from the repository folder)*
```bash
scp -i <your-key.pem> -r deploy ubuntu@<EC2_PUBLIC_IP>:~/sahi-deploy
```

**2. Create the CI deploy key** *(PC)* — see [CI_CD_SETUP.md, step 1](CI_CD_SETUP.md#1-create-a-dedicated-deploy-ssh-key-on-your-pc).

**3. Bootstrap** (installs users, folders, scripts, systemd units, sudo rule, nginx basics; does **not** stop the
running app and does not touch the database)
```bash
sudo bash ~/sahi-deploy/server/bootstrap.sh \
  --public-host <EC2_PUBLIC_IP> \
  --deploy-key "ssh-ed25519 AAAA... github-actions-deploy"
```
It writes `/etc/sahi/sahi.env`, copying `SECRET_KEY` (so nobody is logged out) and the Angel One keys from the old
`/opt/sahi/backend/.env`. Check the variable names (not the values) with `sudo grep -o '^[A-Z_]*=' /etc/sahi/sahi.env`.

**4. Add the GitHub secrets** — [CI_CD_SETUP.md, steps 2–4](CI_CD_SETUP.md#2-record-the-servers-host-key-so-ci-can-detect-a-fake-server).

**5. Push the CI/CD code** to a branch, open a pull request, and wait for CI to pass. **Do not merge yet.**

**6. Migrate the database** (downtime starts here; pick a time outside market hours)
```bash
sudo sahi-migrate-legacy
```
It stops the old service, copies the database with SQLite's backup API (consistent, includes the WAL), runs an
integrity check, stores an extra backup tagged `legacy-migration`, and disables the old service and its nginx site.
The old folder `/opt/sahi/backend` is left untouched.

**7. Deploy**: merge the pull request (or Actions → Deploy → Run workflow). When it is green the site is back.

**8. Check**
```bash
sudo sahi-status
```
Open `http://<EC2_PUBLIC_IP>` and log in with an existing account.

Undo, if needed before step 7 succeeds: `sudo systemctl enable --now sahi`,
`sudo ln -s /etc/nginx/sites-available/sahi /etc/nginx/sites-enabled/sahi && sudo systemctl reload nginx`.
After a successful migration you can delete the old folder later (keep it at least a week):
`sudo rm -rf /opt/sahi/backend /opt/sahi/frontend`.

## B. Brand-new server

1. Launch Ubuntu Server LTS (t3.small or larger; 2 GB RAM recommended), security group as above, 20 GB+ disk.
2. Small instances: add swap so `pip install` cannot run out of memory:
   ```bash
   sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```
3. Copy `deploy/` and run bootstrap exactly as in A.1–A.3.
4. Put the Angel One keys into the env file: `sudo nano /etc/sahi/sahi.env` (see `deploy/server/sahi.env.example`).
5. Allow the first start on an empty database (a safety switch: deploys refuse to create an empty database
   otherwise, so a missing database is never silently replaced):
   ```bash
   sudo touch /var/lib/sahi/.allow-empty-db
   ```
6. Add the GitHub secrets and run the Deploy workflow. Afterwards: `sudo rm /var/lib/sahi/.allow-empty-db`.

## SSH hardening (recommended on any server)

```bash
sudo tee /etc/ssh/sshd_config.d/90-hardening.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo sshd -t && sudo systemctl reload ssh
sudo apt-get install -y unattended-upgrades fail2ban   # automatic security updates, SSH brute-force bans
```

## Re-running bootstrap

Safe at any time. Do it after a pull request changes anything in `deploy/systemd/`, `deploy/server/` or the scripts
in `deploy/bin/` (deploys update the application and nginx site automatically, but not the root-owned ops scripts
and units):

```bash
# (PC) scp -i <your-key.pem> -r deploy ubuntu@<EC2_PUBLIC_IP>:~/sahi-deploy
sudo bash ~/sahi-deploy/server/bootstrap.sh
```
It never overwrites `/etc/sahi/sahi.env`, never touches the database, and never restarts the backend
(run `sudo systemctl restart sahi-backend` yourself if a unit file changed).

#!/usr/bin/env bash
# bootstrap.sh - prepare an Ubuntu EC2 instance for SAHI release deployments. Idempotent: safe to run again,
# e.g. after changing a systemd unit or one of the deploy scripts. Never touches the database, never starts or
# stops the application, never overwrites /etc/sahi/sahi.env.
#
#   sudo bash bootstrap.sh --public-host <ip-or-domain> --deploy-key "<ssh-ed25519 public key for CI>"
#
# Run it from a copy of the repository's deploy/ folder (see docs/AWS_EC2_SETUP.md).
set -Eeuo pipefail
umask 022
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)    # the deploy/ folder
PUBLIC_HOST=""
DEPLOY_KEY=""
while [[ $# -gt 0 ]]; do
  case $1 in
    --public-host) PUBLIC_HOST=$2; shift 2 ;;
    --deploy-key)  DEPLOY_KEY=$2; shift 2 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
log() { printf '[bootstrap] %s\n' "$*"; }
die() { printf '[bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "run with sudo"
[[ -f $HERE/bin/sahi-deploy && -f $HERE/systemd/sahi-backend.service ]] || die "run from the repository's deploy/ folder"
[[ -z $PUBLIC_HOST || $PUBLIC_HOST =~ ^[A-Za-z0-9.:-]+$ ]] || die "--public-host must be an IP address or host name"

log "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx python3 python3-venv curl ca-certificates gzip util-linux >/dev/null
command -v python3 >/dev/null && log "python: $(python3 --version)"

log "users"
id sahi >/dev/null 2>&1 || useradd --system --home-dir /var/lib/sahi --no-create-home --shell /usr/sbin/nologin sahi
if ! id deploy >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash deploy
  passwd -l deploy >/dev/null       # key-only login
fi
install -d -o deploy -g deploy -m 0700 /home/deploy/.ssh
install -d -o deploy -g deploy -m 0750 /home/deploy/incoming
if [[ -n $DEPLOY_KEY ]]; then
  [[ $DEPLOY_KEY =~ ^ssh-(ed25519|rsa)\ [A-Za-z0-9+/=]+(\ .*)?$ ]] || die "--deploy-key does not look like an SSH public key"
  touch /home/deploy/.ssh/authorized_keys
  # restrict the CI key: no port forwarding, no agent/X11 forwarding, no pty
  line="no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty $DEPLOY_KEY"
  grep -qxF "$line" /home/deploy/.ssh/authorized_keys || echo "$line" >>/home/deploy/.ssh/authorized_keys
  chown deploy:deploy /home/deploy/.ssh/authorized_keys
  chmod 0600 /home/deploy/.ssh/authorized_keys
fi

log "directories"
install -d -o root -g root -m 0755 /opt/sahi /opt/sahi/releases
install -d -o root -g sahi -m 0750 /etc/sahi
install -m 0644 "$HERE/server/tmpfiles-sahi.conf" /etc/tmpfiles.d/sahi.conf
systemd-tmpfiles --create /etc/tmpfiles.d/sahi.conf

log "scripts"
install -d -m 0755 /usr/local/lib/sahi
install -m 0644 "$HERE/bin/sahi-common.sh" "$HERE/bin/sahi_sqlite.py" /usr/local/lib/sahi/
for s in sahi-deploy sahi-rollback sahi-backup sahi-restore sahi-monitor sahi-status sahi-migrate-legacy; do
  install -o root -g root -m 0755 "$HERE/bin/$s" "/usr/local/sbin/$s"
done

log "sudoers"
tmp=$(mktemp)
cp "$HERE/server/sudoers-sahi-deploy" "$tmp"
visudo -cqf "$tmp" || die "sudoers file failed validation"
install -o root -g root -m 0440 "$tmp" /etc/sudoers.d/sahi-deploy
rm -f "$tmp"

log "runtime configuration"
if [[ ! -f /etc/sahi/sahi.env ]]; then
  [[ -n $PUBLIC_HOST ]] || die "--public-host is required the first time (to write /etc/sahi/sahi.env)"
  secret=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
  legacy=/opt/sahi/backend/.env
  get_legacy() { [[ -f $legacy ]] && grep -E "^$1=" "$legacy" | tail -n1 | cut -d= -f2- | tr -d '\r' || true; }
  # keep the legacy SECRET_KEY if it is strong (users stay logged in) and the Angel One credentials
  old_secret=$(get_legacy SECRET_KEY)
  (( ${#old_secret} >= 32 )) && secret=$old_secret
  umask 027
  {
    echo "# Written by bootstrap.sh on $(date -u +%F). See deploy/server/sahi.env.example for every option."
    echo "ENVIRONMENT=production"
    echo "DATABASE_URL=sqlite:////var/lib/sahi/sahi.db"
    echo "SECRET_KEY=$secret"
    echo "CORS_ORIGINS=http://$PUBLIC_HOST"
    echo "TRUSTED_HOSTS=$PUBLIC_HOST"
    echo "FEED_MODE=live"
    for k in ANGEL_API_KEY ANGEL_CLIENT_CODE ANGEL_PASSWORD ANGEL_TOTP_SECRET; do echo "$k=$(get_legacy $k)"; done
  } >/etc/sahi/sahi.env
  umask 022
  log "/etc/sahi/sahi.env written (values not shown; Angel One keys copied from $legacy if it existed)"
fi
chown root:sahi /etc/sahi/sahi.env
chmod 0640 /etc/sahi/sahi.env
for f in backup.env monitor.env; do
  [[ -f /etc/sahi/$f ]] || { echo "# optional settings for sahi-${f%.env} - see docs" >"/etc/sahi/$f"; }
  chown root:sahi "/etc/sahi/$f"; chmod 0640 "/etc/sahi/$f"
done

log "systemd units"
for u in sahi-backend.service sahi-backup.service sahi-backup.timer sahi-monitor.service sahi-monitor.timer; do
  install -m 0644 "$HERE/systemd/$u" "/etc/systemd/system/$u"
done
systemctl daemon-reload
systemctl enable sahi-backend.service >/dev/null    # start at boot; not started here
systemctl enable --now sahi-backup.timer sahi-monitor.timer >/dev/null

log "nginx"
systemctl enable --now nginx >/dev/null
rm -f /etc/nginx/sites-enabled/default
if ! grep -q '^\s*server_tokens off' /etc/nginx/nginx.conf; then
  sed -i 's/^\(\s*\)#\s*server_tokens off;/\1server_tokens off;/' /etc/nginx/nginx.conf
fi
nginx -t -q && systemctl reload nginx || die "nginx configuration invalid"

log "journald size cap (500 MB)"
install -d /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=500M\n' >/etc/systemd/journald.conf.d/sahi.conf
systemctl restart systemd-journald

log "done."
if systemctl is-active --quiet sahi.service 2>/dev/null; then
  log "NEXT: the legacy 'sahi' service is running. When ready for a few minutes of downtime run: sudo sahi-migrate-legacy"
  log "      then start the Deploy workflow on GitHub."
elif [[ ! -f /var/lib/sahi/sahi.db ]]; then
  log "NEXT: no database yet. New install? run: sudo touch /var/lib/sahi/.allow-empty-db  - then deploy."
fi

# shellcheck shell=bash disable=SC2034  # variables are used by the scripts that source this file
# Shared helpers for the SAHI server scripts. Installed to /usr/local/lib/sahi/sahi-common.sh by bootstrap.sh.
# Every path and name the scripts use is defined here, once. Nothing in this file prints secrets.

APP_ROOT=/opt/sahi
RELEASES="$APP_ROOT/releases"
CURRENT="$APP_ROOT/current"
STATE_DIR=/var/lib/sahi                 # SQLite database + SmartAPI log folder (service working directory)
DB_FILE="$STATE_DIR/sahi.db"
BACKUP_DIR=/var/backups/sahi
ENV_FILE=/etc/sahi/sahi.env             # runtime secrets, root:sahi 0640, never in Git
LOG_DIR=/var/log/sahi
HISTORY="$LOG_DIR/deploy-history.log"
INCOMING=/home/deploy/incoming          # where CI uploads release tarballs
SERVICE=sahi-backend
APP_USER=sahi
DEPLOY_USER=deploy
NGINX_SITE=/etc/nginx/sites-available/sahi.conf
NGINX_LINK=/etc/nginx/sites-enabled/sahi.conf
BACKEND_URL=http://127.0.0.1:8000
NGINX_URL=http://127.0.0.1
LOCK_FILE=/run/lock/sahi-deploy.lock    # shared by deploy, rollback and restore: one at a time
KEEP_RELEASES=5

log()  { printf '%s [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${SAHI_TAG:-sahi}" "$*"; }
warn() { log "WARNING: $*" >&2; }
die()  { log "ERROR: $*" >&2; exit 1; }

require_root() { [[ $EUID -eq 0 ]] || die "must run as root (use sudo)"; }

take_lock() {
  exec 9>"$LOCK_FILE"
  flock -n 9 || die "another deploy / rollback / restore is running (lock $LOCK_FILE)"
}

history_add() {  # history_add STATUS release-id sha message
  mkdir -p "$LOG_DIR"
  printf '%s\t%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "$3" "$4" >>"$HISTORY"
}

current_release() { [[ -L $CURRENT ]] && readlink -f "$CURRENT" || true; }

# Atomically point /opt/sahi/current at a release directory (rename(2) of a symlink).
switch_to() {
  local target=$1
  [[ -d $target ]] || die "release $target does not exist"
  ln -sfn "$target" "$APP_ROOT/.current.tmp"
  mv -Tf "$APP_ROOT/.current.tmp" "$CURRENT"
  log "current -> $(basename "$target")"
}

# Install the release's nginx site if it differs from the active one. Validates with `nginx -t` and puts the
# old file back if validation fails. Sets NGINX_BACKUP to the saved copy ("" if nothing changed).
NGINX_BACKUP=""
sync_nginx() {
  local release=$1 src="$1/deploy/nginx/sahi.conf"
  NGINX_BACKUP=""
  [[ -f $src ]] || { warn "release has no deploy/nginx/sahi.conf; nginx left unchanged"; return 0; }
  if [[ -f $NGINX_SITE ]] && cmp -s "$src" "$NGINX_SITE" && [[ -L $NGINX_LINK ]]; then
    return 0
  fi
  if [[ -f $NGINX_SITE ]]; then
    NGINX_BACKUP=$(mktemp /var/tmp/sahi-nginx.XXXXXX)
    cp -p "$NGINX_SITE" "$NGINX_BACKUP"
  else
    NGINX_BACKUP=none
  fi
  install -o root -g root -m 0644 "$src" "$NGINX_SITE"
  ln -sfn "$NGINX_SITE" "$NGINX_LINK"
  if ! nginx -t -q 2>/dev/null; then
    nginx -t 2>&1 | sed 's/^/  nginx: /' >&2 || true
    restore_nginx
    return 1
  fi
  systemctl reload nginx
  log "nginx site updated and reloaded ($(basename "$release"))"
}

restore_nginx() {
  [[ -n $NGINX_BACKUP ]] || return 0
  if [[ $NGINX_BACKUP == none ]]; then
    rm -f "$NGINX_LINK" "$NGINX_SITE"
  else
    install -o root -g root -m 0644 "$NGINX_BACKUP" "$NGINX_SITE"
    rm -f "$NGINX_BACKUP"
  fi
  if nginx -t -q 2>/dev/null; then systemctl reload nginx || true; fi
  NGINX_BACKUP=""
  log "nginx site restored"
}

wait_ready() {  # wait_ready seconds - fails fast on a crash loop (2 automatic restarts) instead of waiting it out
  local deadline=$((SECONDS + ${1:-90})) r0 r
  r0=$(systemctl show -p NRestarts --value "$SERVICE")
  while (( SECONDS < deadline )); do
    if curl -fs -m 3 -o /dev/null "$BACKEND_URL/api/health/ready" 2>/dev/null; then return 0; fi
    if systemctl is-failed --quiet "$SERVICE"; then return 1; fi
    r=$(systemctl show -p NRestarts --value "$SERVICE")
    if (( r - r0 >= 2 )); then warn "$SERVICE is crash-looping ($((r - r0)) restarts)"; return 1; fi
    sleep 2
  done
  return 1
}

# Health gate used after every start: backend ready, service active and not crash-looping,
# nginx valid and serving the SPA, an asset of this release, and the API through nginx.
verify_running() {
  local restarts_before restarts_after index asset
  wait_ready 90 || { warn "backend did not become ready"; return 1; }
  restarts_before=$(systemctl show -p NRestarts --value "$SERVICE")
  systemctl is-active --quiet "$SERVICE" || { warn "$SERVICE is not active"; return 1; }
  systemctl is-active --quiet nginx || { warn "nginx is not active"; return 1; }
  nginx -t -q 2>/dev/null || { warn "nginx configuration is invalid"; return 1; }
  index=$(curl -fsS -m 5 "$NGINX_URL/") || { warn "frontend not served by nginx"; return 1; }
  grep -q '<div id="root">' <<<"$index" || { warn "frontend index.html looks wrong"; return 1; }
  asset=$(grep -oE '/assets/[A-Za-z0-9._-]+\.js' <<<"$index" | head -n1)
  if [[ -n $asset ]]; then
    curl -fsS -m 5 -o /dev/null "$NGINX_URL$asset" || { warn "frontend asset $asset not served"; return 1; }
  fi
  curl -fsS -m 5 -o /dev/null "$NGINX_URL/api/health/ready" || { warn "API not reachable through nginx"; return 1; }
  sleep "${SAHI_SETTLE_SECONDS:-10}"   # catch a crash shortly after start (e.g. background threads failing)
  restarts_after=$(systemctl show -p NRestarts --value "$SERVICE")
  systemctl is-active --quiet "$SERVICE" || { warn "$SERVICE stopped after start"; return 1; }
  [[ $restarts_before == "$restarts_after" ]] || { warn "$SERVICE restarted during verification"; return 1; }
  curl -fsS -m 3 -o /dev/null "$BACKEND_URL/api/health/ready" || { warn "backend not ready after settle time"; return 1; }
  return 0
}

stop_service() {
  if systemctl is-active --quiet "$SERVICE"; then
    log "stopping $SERVICE (graceful, up to 30s)"
    systemctl stop "$SERVICE"
  fi
  systemctl reset-failed "$SERVICE" 2>/dev/null || true
}

start_service() {
  log "starting $SERVICE"
  systemctl start "$SERVICE"
}

# Markers inside a release dir: .staged (venv built, smoke boot passed), .deployed (passed the live health gate
# at least once), .failed (failed the live health gate). Rollback only ever targets .deployed releases.
is_good_release() { [[ -f $1/.deployed && ! -f $1/.failed ]]; }

# Newest good release other than the given one (the rollback target).
previous_good_release() {
  local skip=$1 d
  while IFS= read -r d; do
    [[ $d == "$skip" ]] && continue
    is_good_release "$d" && { printf '%s\n' "$d"; return 0; }
  done < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -name '20*' | sort -r)
  return 1
}

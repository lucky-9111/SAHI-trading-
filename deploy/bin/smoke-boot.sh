#!/usr/bin/env bash
# Boot a backend build in production mode against a throwaway SQLite file and probe it, then shut it down.
#   smoke-boot.sh <backend-dir> <python-executable> [port]
# Used by CI (before building the release) and by sahi-deploy (on the staged release, before the live service is
# touched). The environment is wiped (env -i): no broker credentials, FEED_MODE=off and DISABLE_ENGINE=1, so the
# smoke boot can never connect to Angel One, place orders or run the price loop.
set -Eeuo pipefail

BACKEND=$(cd "${1:?backend dir}" && pwd)
PY=${2:?python executable}
[[ $PY == /* ]] || PY="$(cd "$(dirname "$PY")" && pwd)/$(basename "$PY")"   # absolute, but keep the venv path
PORT=${3:-18765}
URL="http://127.0.0.1:$PORT"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/sahi-smoke.XXXXXX")
PID=""

cleanup() {
  if [[ -n $PID ]] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
    kill -9 "$PID" 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

fail() { echo "smoke-boot: FAIL: $*" >&2; echo "--- server output ---" >&2; tail -n 60 "$TMP/server.log" >&2 || true; exit 1; }

if curl -s -m 1 -o /dev/null "$URL/"; then fail "port $PORT is already in use"; fi

SECRET=$("$PY" -c 'import secrets; print(secrets.token_urlsafe(48))')
case "$TMP" in /*) DB_URL="sqlite:///$TMP/smoke.db" ;; *) fail "temp dir must be absolute" ;; esac
# Windows (Git Bash) paths look like /c/...; Python wants C:/...
if command -v cygpath >/dev/null 2>&1; then DB_URL="sqlite:///$(cygpath -m "$TMP")/smoke.db"; fi

(
  cd "$TMP"   # no .env is picked up from here; SmartAPI's ./logs lands in the temp dir
  exec env -i PATH="/usr/bin:/bin:${SYSTEMROOT:+$PATH}" HOME="$TMP" ${SYSTEMROOT:+SYSTEMROOT="$SYSTEMROOT"} \
    ENVIRONMENT=production SECRET_KEY="$SECRET" DATABASE_URL="$DB_URL" \
    CORS_ORIGINS=http://smoke.invalid TRUSTED_HOSTS=smoke.invalid \
    FEED_MODE=off DISABLE_ENGINE=1 DISABLE_AUTO_SYNC=1 PYTHONDONTWRITEBYTECODE=1 \
    "$PY" -m uvicorn app.main:app --app-dir "$BACKEND" --host 127.0.0.1 --port "$PORT" --workers 1 --no-server-header
) >"$TMP/server.log" 2>&1 &
PID=$!

ready=""
for _ in $(seq 1 60); do
  kill -0 "$PID" 2>/dev/null || fail "backend exited during startup"
  if curl -fs -m 2 -o /dev/null "$URL/api/health/ready" 2>/dev/null; then ready=1; break; fi
  sleep 1
done
[[ -n $ready ]] || fail "backend not ready within 60s"

code() { curl -s -m 5 -o /dev/null -w '%{http_code}' "$@"; }
[[ $(code "$URL/api/health/live") == 200 ]]                     || fail "/api/health/live"
[[ $(code "$URL/api/health/ready") == 200 ]]                    || fail "/api/health/ready"
[[ $(code "$URL/api/health") == 200 ]]                          || fail "/api/health"
[[ $(code "$URL/api/auth/me") == 401 ]]                         || fail "protected route should answer 401 without a token"
[[ $(code "$URL/docs") == 404 ]]                                || fail "API docs must be disabled in production"
[[ $(code "$URL/openapi.json") == 404 ]]                        || fail "OpenAPI schema must be disabled in production"
[[ $(code -H 'Host: attacker.invalid' "$URL/api/health") == 400 ]] || fail "untrusted Host header must be rejected"
[[ $(code -H 'Host: smoke.invalid' "$URL/api/health") == 200 ]] || fail "trusted Host header must be accepted"
grep -qi "Traceback" "$TMP/server.log" && fail "traceback in server output"

echo "smoke-boot: OK (production settings, health, auth guard, docs off, host check)"

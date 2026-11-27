#!/usr/bin/env bash
# build-release.sh <output-dir>
# Package the checked-out commit for deployment: tracked backend + deploy + docs files (git archive: untracked
# files such as .env, *.db, logs and node_modules can never get in), plus the built frontend/dist.
# Output: <output-dir>/sahi-<sha>.tar.gz and <output-dir>/sahi-<sha>.tar.gz.sha256
# Requires: a clean git checkout and `npm run build` already done in frontend/.
set -Eeuo pipefail
OUT=${1:?output dir}
ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
SHA=$(git rev-parse HEAD)
[[ -f frontend/dist/index.html ]] || { echo "frontend/dist missing - run npm run build first" >&2; exit 1; }
if [[ -n $(git status --porcelain --untracked-files=no) ]]; then
  echo "working tree has uncommitted changes to tracked files; refusing to package (the tarball must equal $SHA)" >&2
  exit 1
fi

mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

git archive --format=tar HEAD backend deploy docs \
  ':(exclude)backend/tests' ':(exclude)backend/.env.example' | tar -x -C "$STAGE"
mkdir -p "$STAGE/frontend"
cp -R frontend/dist "$STAGE/frontend/dist"
printf '%s\n' "$SHA" >"$STAGE/REVISION"
printf 'commit=%s\nbuilt_at=%s\nrun=%s\n' "$SHA" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${GITHUB_RUN_ID:-local}" >"$STAGE/BUILD_INFO"

# last line of defence: never ship secrets or databases
if find "$STAGE" \( -name '.env' -o -name '*.db' -o -name '*.db-*' -o -name '*.pem' -o -name '*.key' -o -name 'angelone_credentials.json' \) -print | grep .; then
  echo "refusing to package: secret or database file found (listed above)" >&2
  exit 1
fi

NAME="sahi-$SHA.tar.gz"
tar -C "$STAGE" --owner=0 --group=0 --numeric-owner -czf "$OUT/$NAME" .
( cd "$OUT" && sha256sum "$NAME" >"$NAME.sha256" )
echo "built $OUT/$NAME ($(du -h "$OUT/$NAME" | cut -f1)) sha256=$(cut -d' ' -f1 "$OUT/$NAME.sha256")"

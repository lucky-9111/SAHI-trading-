#!/usr/bin/env bash
# Fail if secrets, keys or databases are tracked in Git, or a private key / cloud key appears in tracked text.
# Runs in CI (security workflow) and locally: bash deploy/ci/check-repo-hygiene.sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
fail=0

bad_names=$(git ls-files | grep -Ei '(^|/)(\.env(\..+)?|.*\.pem|.*\.key|.*\.p12|.*\.pfx|.*\.db|.*\.db-(wal|shm)|.*\.sqlite3?|id_(rsa|ed25519|ecdsa)(\.pub)?|angelone_credentials\.json|.*\.tfstate(\.backup)?)$' \
  | grep -Ev '(^|/)\.env\.example$' || true)
if [[ -n $bad_names ]]; then
  echo "::error::Tracked files that must never be committed (secrets / keys / databases):"
  echo "$bad_names" | sed 's/^/  /'
  fail=1
fi

# Content patterns: private key blocks, AWS access keys, GitHub tokens. Prints file:line only, never the match.
patterns='-----BEGIN ([A-Z]+ )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}'
set +e
raw=$(git grep -nIE -e "$patterns" -- . ':(exclude)deploy/ci/check-repo-hygiene.sh')
rc=$?
set -e
(( rc <= 1 )) || { echo "::error::git grep failed (exit $rc)"; exit 2; }   # 1 = no match, >1 = error
hits=$(cut -d: -f1,2 <<<"$raw" | sed '/^$/d')
if [[ -n $hits ]]; then
  echo "::error::Possible credentials in tracked files (file:line):"
  echo "$hits" | sed 's/^/  /'
  fail=1
fi

if (( fail )); then
  echo "Remove the file from Git (git rm --cached <file>), rotate the credential, and see docs/PRODUCTION_SECURITY.md."
  exit 1
fi
echo "repo hygiene: OK (no tracked secrets, keys or databases)"

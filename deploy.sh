#!/usr/bin/env bash
set -e
BRANCH="${BRANCH:-main}"
MSG="${1:-chore: deploy 2025-10-08 15:23:45}"

git checkout "$BRANCH"

git add -A
git commit -m "$MSG" || true

git fetch
git pull --rebase
git push origin "$BRANCH"

[ -n "$DEPLOY_HOOK_URL" ] && curl -fsSL -X POST "$DEPLOY_HOOK_URL" >/dev/null 2>&1 || true


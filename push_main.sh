#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

msg=${1:-"Update check-ins and touchpoints"}

git status -sb

git add -A

git commit -m "$msg" || true

git push origin main

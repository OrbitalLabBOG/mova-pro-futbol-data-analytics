#!/usr/bin/env bash
set -euo pipefail
repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
exec "$repo_dir/deploy/bin/mova" maintenance backups --apply \
  --actor mova-backup-retention --reason 'Daily bounded local retention (7-14 days); preserve two verified sets per family' \
  --idempotency-key "scheduled-backup-retention:$(date -u +%Y-%m-%d)"

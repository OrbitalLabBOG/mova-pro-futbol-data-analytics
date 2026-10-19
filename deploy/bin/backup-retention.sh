#!/usr/bin/env bash
set -euo pipefail
repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
exec "$repo_dir/deploy/bin/mova" maintenance backups --apply \
  --actor mova-backup-retention --reason 'Hourly bounded local retention; preserve two verified sets per family' \
  --idempotency-key "scheduled-backup-retention:$(date -u +%Y-%m-%dT%H)"

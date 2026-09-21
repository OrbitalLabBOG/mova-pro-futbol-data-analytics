#!/usr/bin/env bash
set -euo pipefail

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
backup_dir=${1:?usage: restore-drill.sh /opt/orbital/backups/mova-fpl/TIMESTAMP}
test -f "$backup_dir/manifest.json"
test -f "$backup_dir/ops.db"

docker compose --project-directory "$repo_dir" -f "$repo_dir/compose.yaml" \
  --profile jobs run --rm --no-deps \
  -v "$backup_dir:/restore:ro" worker \
  sh -c 'cp /restore/ops.db /tmp/mova-restore-ops.db && \
    MOVA_OPS_DB=/tmp/mova-restore-ops.db python -m mova_fpl.ops.cli check'
echo "restore drill passed for $backup_dir"

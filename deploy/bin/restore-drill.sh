#!/usr/bin/env bash
set -euo pipefail

deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}
backup_dir=${1:?usage: restore-drill.sh BACKUP_DIRECTORY}
if [[ -r "$deploy_env" ]]; then
  set -a
  source "$deploy_env"
  set +a
fi
backup_dir=$(realpath -e "$backup_dir")
test -f "$backup_dir/manifest.json"
# Bypass production Compose: no runtime mounts, network or secrets.
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --mount "type=bind,src=$backup_dir,dst=/restore,readonly" \
  --entrypoint python "mova-fpl-engine:${MOVA_IMAGE_TAG:?deploy image tag required}" \
  -m mova_fpl.ops.sqlite_restore /restore
echo "complete SQLite restore drill passed"

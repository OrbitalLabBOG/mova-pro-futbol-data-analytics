#!/usr/bin/env bash
set -euo pipefail

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}

if [[ -r "$deploy_env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$deploy_env"
  set +a
fi

cd "$repo_dir"
docker compose --profile jobs run --rm --no-deps -T worker \
  python -m mova_fpl.ops.cli backup --retention-days 35
deploy/bin/postgres-shadow-backup.sh

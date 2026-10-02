#!/usr/bin/env bash
set -euo pipefail

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}
backup_root=${MOVA_BACKUP_ROOT:-/opt/orbital/backups/mova-fpl}
retention_days=${MOVA_POSTGRES_BACKUP_RETENTION_DAYS:-35}

if [[ -r "$deploy_env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$deploy_env"
  set +a
fi

postgres_db=${MOVA_POSTGRES_DB:-mova}
postgres_user=${MOVA_POSTGRES_USER:-mova_owner}
backup_root=${MOVA_BACKUP_ROOT:-$backup_root}/postgres
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
partial="$backup_root/.${timestamp}.partial"
destination="$backup_root/$timestamp"

install -d -m 0750 "$backup_root"
install -d -m 0750 "$partial"
postgres_container=''
original_cpus=''
cleanup() {
  if [[ -n "$original_cpus" ]]; then
    docker update --cpus "$original_cpus" "$postgres_container" >/dev/null
  fi
  rm -rf -- "$partial"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

cd "$repo_dir"
# The steady-state 0.10 CPU cap cannot finish the full content inventory within
# the backup service's 900 s window. Borrow bounded capacity for this job only.
postgres_container=$(docker compose ps -q postgres)
[[ -n "$postgres_container" ]]
current_nano=$(docker inspect "$postgres_container" --format '{{.HostConfig.NanoCpus}}')
backup_cpus=${MOVA_POSTGRES_BACKUP_CPUS:-0.50}
original_cpus=$(python3 - "$current_nano" "$backup_cpus" <<'PY'
import math
import sys
current = int(sys.argv[1])
target = float(sys.argv[2])
if not math.isfinite(target) or not 0 < target <= 0.50:
    raise SystemExit('backup CPU budget must be greater than zero and at most 0.50')
if 0 < current < round(target * 1_000_000_000):
    print(f'{current / 1_000_000_000:.9f}')
PY
)
if [[ -n "$original_cpus" ]]; then
  docker update --cpus "$backup_cpus" "$postgres_container" >/dev/null
fi
git_sha=$(git rev-parse --short HEAD)
python3 -m mova_fpl.ops.postgres_backup backup "$partial" \
  --database "$postgres_db" --user "$postgres_user" --revision "$git_sha"
# Validate the archive catalog before publishing the sealed set.
docker compose exec -T postgres pg_restore --list < "$partial/postgres-shadow.dump" >/dev/null
chmod 0640 "$partial/postgres-shadow.dump" "$partial/manifest.json"
mv "$partial" "$destination"

while IFS= read -r expired; do
  [[ "$expired" == "$backup_root"/20??????T??????Z ]]
  rm -rf -- "$expired"
done < <(find "$backup_root" -mindepth 1 -maxdepth 1 -type d \
  -name '20??????T??????Z' -mtime "+$retention_days" -print)
echo "$destination"

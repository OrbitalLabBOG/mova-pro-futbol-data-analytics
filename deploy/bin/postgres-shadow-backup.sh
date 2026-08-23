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
cleanup() { rm -rf -- "$partial"; }
trap cleanup EXIT

cd "$repo_dir"
docker compose exec -T postgres \
  pg_dump --format=custom --no-owner --no-acl \
  --username="$postgres_user" --dbname="$postgres_db" > "$partial/postgres-shadow.dump"
docker compose exec -T postgres pg_restore --list < "$partial/postgres-shadow.dump" >/dev/null

dump_sha256=$(sha256sum "$partial/postgres-shadow.dump" | awk '{print $1}')
dump_bytes=$(stat -c '%s' "$partial/postgres-shadow.dump")
git_sha=$(git rev-parse HEAD)
python3 - "$partial/manifest.json" "$timestamp" "$git_sha" "$postgres_db" \
  "$dump_sha256" "$dump_bytes" <<'PY'
import json
import sys

path, created_at, git_sha, database, sha256, size = sys.argv[1:]
payload = {
    "schema": "mova-postgres-backup-v1",
    "created_at": created_at,
    "git_sha": git_sha,
    "database": database,
    "dump": {"name": "postgres-shadow.dump", "sha256": sha256, "bytes": int(size)},
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
PY
chmod 0640 "$partial/postgres-shadow.dump" "$partial/manifest.json"
mv "$partial" "$destination"
trap - EXIT

while IFS= read -r expired; do
  [[ "$expired" == "$backup_root"/20????????T??????Z ]]
  rm -rf -- "$expired"
done < <(find "$backup_root" -mindepth 1 -maxdepth 1 -type d \
  -name '20????????T??????Z' -mtime "+$retention_days" -print)
echo "$destination"

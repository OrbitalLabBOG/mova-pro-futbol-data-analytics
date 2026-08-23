#!/usr/bin/env bash
set -euo pipefail

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}
backup_dir=${1:?usage: postgres-shadow-restore-drill.sh BACKUP_DIRECTORY}

if [[ -r "$deploy_env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$deploy_env"
  set +a
fi

postgres_user=${MOVA_POSTGRES_USER:-mova_owner}
dump="$backup_dir/postgres-shadow.dump"
manifest="$backup_dir/manifest.json"
test -f "$dump"
test -f "$manifest"

expected_sha256=$(python3 - "$manifest" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["dump"]["sha256"])
PY
)
observed_sha256=$(sha256sum "$dump" | awk '{print $1}')
test "$observed_sha256" = "$expected_sha256"

restore_db="mova_restore_$(date -u +%Y%m%d%H%M%S)_$$"
[[ "$restore_db" =~ ^mova_restore_[0-9]+_[0-9]+$ ]]
cd "$repo_dir"
cleanup() {
  docker compose exec -T postgres dropdb --if-exists \
    --username="$postgres_user" "$restore_db" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose exec -T postgres createdb --template=template0 \
  --username="$postgres_user" "$restore_db"
docker compose exec -T postgres pg_restore --exit-on-error --no-owner --no-acl \
  --username="$postgres_user" --dbname="$restore_db" < "$dump"

result=$(docker compose exec -T postgres psql --no-psqlrc --tuples-only --no-align \
  --username="$postgres_user" --dbname="$restore_db" --command="
    select case
      when count(*) = 7
       and to_regclass('mova_meta.schema_migrations') is not null
       and to_regclass('analytics.player_gameweek') is not null
       and to_regclass('ops.audit_events') is not null
      then 'pass' else 'fail' end
    from information_schema.schemata
    where schema_name in ('mova_meta','raw','analytics','game','research','agent','ops');")
test "$result" = "pass"
echo "restore drill passed: $backup_dir -> $restore_db (temporary database removed)"

#!/usr/bin/env bash
set -euo pipefail

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}
actor=${1:?usage: postgres-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY}
reason=${2:?usage: postgres-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY}
idempotency_key=${3:?usage: postgres-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY}

set -a
source "$deploy_env"
set +a
cd "$repo_dir"

# The dedicated drill lock prevents duplicate outages. The service locks keep
# every scheduled writer that depends on PostgreSQL out of the outage window.
exec {drill_fd}>/run/lock/mova-fpl-postgres-recovery-drill.lock
flock -n "$drill_fd" || { echo "another PostgreSQL recovery drill is running" >&2; exit 75; }

set +e
existing=$(/usr/local/bin/mova drill host-status --scenario postgres_recovery \
  --actor "$actor" --reason "$reason" --idempotency-key "$idempotency_key")
existing_rc=$?
set -e
if [[ "$existing_rc" -eq 0 ]]; then
  echo "$existing"
  exit 0
fi
if [[ "$existing_rc" -ne 75 ]]; then
  echo "$existing" >&2
  exit "$existing_rc"
fi

# Replays and identity conflicts return before competing with scheduled work.
for lock_file in \
  /run/lock/mova-fpl-worker.lock \
  /run/lock/mova-fpl-collector-host.lock \
  /run/lock/mova-fpl-analytics-host.lock \
  /run/lock/mova-fpl-research-host.lock \
  /run/lock/mova-fpl-private-state.lock
do
  exec {service_fd}>"$lock_file"
  if ! flock -n "$service_fd"; then
    echo "dependent service is active; PostgreSQL drill deferred: $lock_file" >&2
    exit 75
  fi
done

artifact_root=${MOVA_DATA_ROOT:-/var/lib/mova-fpl}/artifacts
ops_db=${MOVA_DATA_ROOT:-/var/lib/mova-fpl}/db/ops.db
inbox="$artifact_root/host-drills/inbox"
imported="$artifact_root/host-drills/imported"
revision=$(git rev-parse --short HEAD)
started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
started_epoch=$(date -u +%s)
recovered=0

install -d -m 0750 -o 10001 -g 10001 "$inbox" "$imported"
[[ -w "$inbox" && -w "$imported" ]]

team_state_hash() {
  docker compose --profile jobs run --rm --no-deps -T --entrypoint python \
    worker - "$ops_db" <<'PY'
import hashlib
import json
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
try:
    row = connection.execute(
        "SELECT * FROM team_state_snapshots ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
finally:
    connection.close()
if row is None:
    raise SystemExit("team state snapshot missing")
encoded = json.dumps(list(row), default=str, ensure_ascii=False,
                     separators=(",", ":")).encode()
print(hashlib.sha256(encoded).hexdigest())
PY
}

sqlite_integrity() {
  docker compose --profile jobs run --rm --no-deps -T --entrypoint python \
    worker - "$ops_db" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
try:
    result = connection.execute("PRAGMA quick_check").fetchone()
finally:
    connection.close()
if not result or result[0] != "ok":
    raise SystemExit("SQLite quick_check failed")
print("ok")
PY
}

postgres_ready() {
  docker compose exec -T postgres sh -c \
    'pg_isready -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}

recover_postgres() {
  if [[ "$recovered" -eq 0 ]]; then
    docker compose up -d --no-deps postgres >/dev/null 2>&1 || true
  fi
}
trap recover_postgres EXIT

postgres_ready
curl --fail --silent --show-error \
  "http://127.0.0.1:${MOVA_API_PORT:-8787}/readyz" >/dev/null
/usr/local/bin/mova postgres verify >/dev/null
team_before=$(team_state_hash)
postgres_image_before=$(docker inspect --format '{{.Image}}' mova-fpl-postgres-1)

outage_started_epoch=$(date -u +%s)
docker compose stop --timeout 20 postgres >/dev/null
if timeout 20 /usr/local/bin/mova postgres status >/dev/null 2>&1; then
  echo "PostgreSQL remained reachable during outage drill" >&2
  exit 1
fi
curl --fail --silent --show-error \
  "http://127.0.0.1:${MOVA_API_PORT:-8787}/readyz" >/dev/null
[[ "$(sqlite_integrity)" == "ok" ]]
team_during=$(team_state_hash)
[[ "$team_during" == "$team_before" ]]

docker compose up -d --no-deps postgres >/dev/null
for _attempt in $(seq 1 60); do
  if postgres_ready; then
    recovered=1
    break
  fi
  sleep 2
done
[[ "$recovered" -eq 1 ]]
downtime_seconds=$(( $(date -u +%s) - outage_started_epoch ))

/usr/local/bin/mova postgres verify >/dev/null
team_after=$(team_state_hash)
[[ "$team_after" == "$team_before" ]]
postgres_image_after=$(docker inspect --format '{{.Image}}' mova-fpl-postgres-1)
[[ "$postgres_image_after" == "$postgres_image_before" ]]
image_revision=$(docker inspect mova-fpl-api-1 --format \
  '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
[[ "$image_revision" == "$revision" ]]

finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
host_path="$inbox/postgres-recovery-${revision}-${started_epoch}.json"
python3 - "$host_path" "$started_at" "$finished_at" "$downtime_seconds" \
  "$revision" "$team_before" "$team_after" <<'PY'
import json
import os
import sys

path, started, finished, duration, revision, team_before, team_after = sys.argv[1:]
payload = {
    "schema": "mova-host-drill-v1", "scenario": "postgres_recovery",
    "status": "pass", "started_at": started, "finished_at": finished,
    "downtime_seconds": int(duration), "revision": revision,
    "checks": {
        "postgres_ready_before": True,
        "postgres_unavailable_during": True,
        "api_ready_during": True,
        "sqlite_integrity_during": True,
        "postgres_ready_after": True,
        "postgres_parity_after": True,
        "revision_unchanged": True,
        "team_state_unchanged": True,
    },
    "team_state_sha256_before": team_before,
    "team_state_sha256_after": team_after,
    "fpl_state_mutated": False,
}
temporary = f"{path}.tmp"
with open(temporary, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(temporary, 0o640)
try:
    os.chown(temporary, 10001, 10001)
except PermissionError:
    pass
os.replace(temporary, path)
PY

/usr/local/bin/mova drill import-host --file "$host_path" --actor "$actor" \
  --reason "$reason" --scenario postgres_recovery \
  --idempotency-key "$idempotency_key"

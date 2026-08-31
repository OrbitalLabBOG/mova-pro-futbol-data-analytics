#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}
actor=${1:?usage: combined-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY}
reason=${2:?usage: combined-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY}
idempotency_key=${3:?usage: combined-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY}

set -a
source "$deploy_env"
set +a
cd "$repo_dir"

exec {drill_fd}>/run/lock/mova-fpl-combined-recovery-drill.lock
flock -n "$drill_fd" || { echo "another combined recovery drill is running" >&2; exit 75; }
for lock_file in \
  /run/lock/mova-fpl-worker.lock \
  /run/lock/mova-fpl-collector-host.lock \
  /run/lock/mova-fpl-analytics-host.lock \
  /run/lock/mova-fpl-research-host.lock \
  /run/lock/mova-fpl-private-state.lock
do
  exec {service_fd}>"$lock_file"
  flock -n "$service_fd" || {
    echo "dependent service is active; combined drill deferred: $lock_file" >&2
    exit 75
  }
done

set +e
existing=$(/usr/local/bin/mova drill host-status --scenario combined_recovery \
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

artifact_root=${MOVA_DATA_ROOT:-/var/lib/mova-fpl}/artifacts
ops_db=${MOVA_DATA_ROOT:-/var/lib/mova-fpl}/db/ops.db
inbox="$artifact_root/host-drills/inbox"
imported="$artifact_root/host-drills/imported"
browser_session="$repo_dir/deploy/bin/browser-session.sh"
api_url="http://127.0.0.1:${MOVA_API_PORT:-8787}/readyz"
revision=$(git rev-parse --short HEAD)
started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
started_epoch=$(date -u +%s)
work_dir=$(mktemp -d /run/mova-combined-recovery.XXXXXX)
before_state="$work_dir/before.json"
after_state="$work_dir/after.json"
initial_browser_running=0
if docker inspect --format '{{.State.Running}}' mova-fpl-browser-1 \
  2>/dev/null | grep -qx true; then
  initial_browser_running=1
fi

restore_services() {
  local status=$?
  trap - EXIT HUP INT TERM
  set +e
  docker compose up -d --no-deps postgres >/dev/null 2>&1
  docker compose up -d --no-deps api >/dev/null 2>&1
  if [[ "$initial_browser_running" -eq 1 ]]; then
    "$browser_session" start >/dev/null 2>&1
  else
    "$browser_session" stop >/dev/null 2>&1
  fi
  rm -f "$before_state" "$after_state"
  rmdir "$work_dir" >/dev/null 2>&1 || true
  exit "$status"
}
trap restore_services EXIT HUP INT TERM

install -d -m 0750 -o 10001 -g 10001 "$inbox" "$imported"
[[ -w "$inbox" && -w "$imported" ]]

browser_ready() {
  curl -fsS --max-time 2 "http://127.0.0.1:${MOVA_NOVNC_PORT:-6080}/vnc.html" \
    >/dev/null 2>&1 \
    && docker compose --profile browser exec -T browser \
      curl -fsS --max-time 2 "http://127.0.0.1:${MOVA_BROWSER_CDP_PORT:-9222}/json/version" \
      >/dev/null 2>&1
}

postgres_ready() {
  docker compose exec -T postgres sh -c \
    'pg_isready -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}

state_fingerprint() {
  docker compose --profile jobs run --rm --no-deps -T --entrypoint python \
    worker -c 'import json,sys
from mova_fpl.data.private_state import validate
_, quality = validate(json.load(sys.stdin), expected_team_id=int(sys.argv[1]))
print(quality["fingerprint"])' "${MOVA_TEAM_ID:-3609854}"
}

stored_team_hash() {
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
print(hashlib.sha256(json.dumps(list(row), default=str, ensure_ascii=False,
      separators=(",", ":")).encode()).hexdigest())
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

controls_fingerprint() {
  /usr/local/bin/mova safety | tail -n 1 | python3 -c 'import hashlib,json,sys
p=json.load(sys.stdin); c=p.get("controls") or {}
expected={"action_level":"A0","browser_writes":False,"compliance_gate":"pending","kill_switch":True,"mode":"shadow"}
if c != expected: raise SystemExit("combined drill requires fail-closed A0 controls")
print(hashlib.sha256(json.dumps(c,sort_keys=True,separators=(",",":")).encode()).hexdigest())'
}

controls_before=$(controls_fingerprint)
curl --fail --silent --show-error "$api_url" >/dev/null
postgres_ready
/usr/local/bin/mova postgres verify >/dev/null
"$browser_session" start >/dev/null
browser_ready
"$browser_session" collect >"$before_state"
private_before=$(state_fingerprint <"$before_state")
stored_before=$(stored_team_hash)
api_image=$(docker inspect mova-fpl-api-1 --format '{{.Image}}')
postgres_image=$(docker inspect mova-fpl-postgres-1 --format '{{.Image}}')
browser_image=$(docker inspect mova-fpl-browser-1 --format '{{.Image}}')
api_revision=$(docker inspect mova-fpl-api-1 --format \
  '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
browser_revision=$(docker inspect mova-fpl-browser-1 --format \
  '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
[[ "$api_revision" == "$revision" && "$browser_revision" == "$revision" ]]

outage_started_epoch=$(date -u +%s)
docker compose --profile browser stop --timeout 20 browser >/dev/null
docker compose stop --timeout 10 api >/dev/null
docker compose stop --timeout 20 postgres >/dev/null
if browser_ready || curl -fsS --max-time 2 "$api_url" >/dev/null 2>&1 \
  || timeout 15 /usr/local/bin/mova postgres status >/dev/null 2>&1; then
  echo "one or more services remained reachable during combined outage" >&2
  exit 1
fi
[[ "$(sqlite_integrity)" == "ok" ]]
stored_during=$(stored_team_hash)
[[ "$stored_during" == "$stored_before" ]]

docker compose up -d --no-deps postgres >/dev/null
for _attempt in $(seq 1 60); do
  postgres_ready && break
  sleep 2
done
postgres_ready
docker compose up -d --no-deps api >/dev/null
for _attempt in $(seq 1 45); do
  curl -fsS --max-time 2 "$api_url" >/dev/null 2>&1 && break
  sleep 2
done
curl --fail --silent --show-error "$api_url" >/dev/null
"$browser_session" start >/dev/null
browser_ready
downtime_seconds=$(( $(date -u +%s) - outage_started_epoch ))

/usr/local/bin/mova postgres verify >/dev/null
"$browser_session" collect >"$after_state"
private_after=$(state_fingerprint <"$after_state")
[[ "$private_after" == "$private_before" ]]
stored_after=$(stored_team_hash)
[[ "$stored_after" == "$stored_before" ]]
[[ "$(docker inspect mova-fpl-api-1 --format '{{.Image}}')" == "$api_image" ]]
[[ "$(docker inspect mova-fpl-postgres-1 --format '{{.Image}}')" == "$postgres_image" ]]
[[ "$(docker inspect mova-fpl-browser-1 --format '{{.Image}}')" == "$browser_image" ]]
[[ "$(controls_fingerprint)" == "$controls_before" ]]

if [[ "$initial_browser_running" -eq 0 ]]; then
  "$browser_session" stop >/dev/null
  ! docker inspect --format '{{.State.Running}}' mova-fpl-browser-1 \
    2>/dev/null | grep -qx true
else
  "$browser_session" start >/dev/null
  browser_ready
fi

finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
host_path="$inbox/combined-recovery-${revision}-${started_epoch}.json"
python3 - "$host_path" "$started_at" "$finished_at" "$downtime_seconds" \
  "$revision" "$private_before" "$private_after" <<'PY'
import json
import os
import sys

path, started, finished, duration, revision, before, after = sys.argv[1:]
payload = {
    "schema": "mova-host-drill-v1", "scenario": "combined_recovery",
    "status": "pass", "started_at": started, "finished_at": finished,
    "downtime_seconds": int(duration), "revision": revision,
    "checks": {
        "services_ready_before": True,
        "all_services_unavailable_during": True,
        "sqlite_integrity_during": True,
        "stored_team_state_unchanged_during": True,
        "postgres_ready_after": True,
        "postgres_parity_after": True,
        "api_ready_after": True,
        "browser_ready_after": True,
        "session_authenticated_after": True,
        "revisions_unchanged": True,
        "private_state_unchanged": True,
        "controls_fail_closed": True,
        "initial_browser_state_restored": True,
    },
    "team_state_sha256_before": before,
    "team_state_sha256_after": after,
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

rm -f "$before_state" "$after_state"
/usr/local/bin/mova drill import-host --file "$host_path" --actor "$actor" \
  --reason "$reason" --scenario combined_recovery \
  --idempotency-key "$idempotency_key"

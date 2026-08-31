#!/usr/bin/env bash
set -euo pipefail

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}
actor=${1:?usage: api-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY}
reason=${2:?usage: api-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY}
idempotency_key=${3:?usage: api-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY}

set -a
source "$deploy_env"
set +a
cd "$repo_dir"

exec 9>/run/lock/mova-fpl-api-recovery-drill.lock
if ! flock -n 9; then
  echo "another API recovery drill is running" >&2
  exit 75
fi

set +e
existing=$(/usr/local/bin/mova drill host-status --idempotency-key "$idempotency_key")
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

api_url="http://127.0.0.1:${MOVA_API_PORT:-8787}/readyz"
artifact_root=${MOVA_DATA_ROOT:-/var/lib/mova-fpl}/artifacts
inbox="$artifact_root/host-drills/inbox"
revision=$(git rev-parse --short HEAD)
started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
started_epoch=$(date -u +%s)
recovered=0

recover_api() {
  if [[ "$recovered" -eq 0 ]]; then
    docker compose up -d --no-deps api >/dev/null 2>&1 || true
  fi
}
trap recover_api EXIT

curl --fail --silent --show-error "$api_url" >/dev/null
docker compose stop --timeout 10 api >/dev/null
if curl --fail --silent --max-time 2 "$api_url" >/dev/null 2>&1; then
  echo "API remained reachable during outage drill" >&2
  exit 1
fi
docker compose up -d --no-deps api >/dev/null
for _attempt in $(seq 1 30); do
  if curl --fail --silent --max-time 2 "$api_url" >/dev/null 2>&1; then
    recovered=1
    break
  fi
  sleep 2
done
[[ "$recovered" -eq 1 ]]
/usr/local/bin/mova check >/dev/null
image_revision=$(docker inspect mova-fpl-api-1 --format \
  '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
[[ "$image_revision" == "$revision" ]]

finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
downtime_seconds=$(( $(date -u +%s) - started_epoch ))
install -d -m 0750 -o 10001 -g 10001 "$inbox"
host_path="$inbox/api-recovery-${revision}-${started_epoch}.json"
python3 - "$host_path" "$started_at" "$finished_at" "$downtime_seconds" "$revision" <<'PY'
import json
import os
import sys

path, started, finished, duration, revision = sys.argv[1:]
payload = {
    "schema": "mova-host-drill-v1", "scenario": "api_recovery", "status": "pass",
    "started_at": started, "finished_at": finished,
    "downtime_seconds": int(duration), "revision": revision,
    "checks": {
        "ready_before": True, "unavailable_during": True, "ready_after": True,
        "revision_unchanged": True, "sqlite_integrity_after": True,
    },
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
  --reason "$reason" --idempotency-key "$idempotency_key"

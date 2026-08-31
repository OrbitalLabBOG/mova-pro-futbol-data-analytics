#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}
actor=${1:?usage: browser-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY}
reason=${2:?usage: browser-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY}
idempotency_key=${3:?usage: browser-recovery-drill.sh ACTOR REASON IDEMPOTENCY_KEY}

set -a
source "$deploy_env"
set +a
cd "$repo_dir"

exec {drill_fd}>/run/lock/mova-fpl-browser-recovery-drill.lock
flock -n "$drill_fd" || { echo "another browser recovery drill is running" >&2; exit 75; }
exec {private_fd}>/run/lock/mova-fpl-private-state.lock
flock -n "$private_fd" || { echo "private-state collector is active; browser drill deferred" >&2; exit 75; }

set +e
existing=$(/usr/local/bin/mova drill host-status --scenario browser_recovery \
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
inbox="$artifact_root/host-drills/inbox"
imported="$artifact_root/host-drills/imported"
browser_session="$repo_dir/deploy/bin/browser-session.sh"
revision=$(git rev-parse --short HEAD)
started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
started_epoch=$(date -u +%s)
work_dir=$(mktemp -d /run/mova-browser-recovery.XXXXXX)
before_state="$work_dir/before.json"
after_state="$work_dir/after.json"
initial_running=0
if docker inspect --format '{{.State.Running}}' mova-fpl-browser-1 \
  2>/dev/null | grep -qx true; then
  initial_running=1
fi

restore_initial_state() {
  local status=$?
  trap - EXIT HUP INT TERM
  set +e
  if [[ "$initial_running" -eq 1 ]]; then
    "$browser_session" start >/dev/null 2>&1
  else
    "$browser_session" stop >/dev/null 2>&1
  fi
  rm -f "$before_state" "$after_state"
  rmdir "$work_dir" >/dev/null 2>&1 || true
  exit "$status"
}
trap restore_initial_state EXIT HUP INT TERM

install -d -m 0750 -o 10001 -g 10001 "$inbox" "$imported"
[[ -w "$inbox" && -w "$imported" ]]

state_fingerprint() {
  docker compose --profile jobs run --rm --no-deps -T --entrypoint python \
    worker -c 'import json,sys
from mova_fpl.data.private_state import validate
_, quality = validate(json.load(sys.stdin), expected_team_id=int(sys.argv[1]))
print(quality["fingerprint"])' "${MOVA_TEAM_ID:-3609854}"
}

controls_fingerprint() {
  /usr/local/bin/mova safety | tail -n 1 | python3 -c 'import hashlib,json,sys
p=json.load(sys.stdin); c=p.get("controls") or {}
expected={"action_level":"A0","browser_writes":False,"compliance_gate":"pending","kill_switch":True,"mode":"shadow"}
if c != expected: raise SystemExit("browser recovery drill requires fail-closed A0 controls")
print(hashlib.sha256(json.dumps(c,sort_keys=True,separators=(",",":")).encode()).hexdigest())'
}

browser_ready() {
  curl -fsS --max-time 2 "http://127.0.0.1:${MOVA_NOVNC_PORT:-6080}/vnc.html" \
    >/dev/null 2>&1 \
    && docker compose --profile browser exec -T browser \
      curl -fsS --max-time 2 "http://127.0.0.1:${MOVA_BROWSER_CDP_PORT:-9222}/json/version" \
      >/dev/null 2>&1
}

browser_running() {
  docker inspect --format '{{.State.Running}}' mova-fpl-browser-1 \
    2>/dev/null | grep -qx true
}

controls_before=$(controls_fingerprint)
"$browser_session" start >/dev/null
browser_ready
"$browser_session" collect >"$before_state"
team_before=$(state_fingerprint <"$before_state")
image_before=$(docker inspect mova-fpl-browser-1 --format '{{.Image}}')
image_revision_before=$(docker inspect mova-fpl-browser-1 --format \
  '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
[[ "$image_revision_before" == "$revision" ]]

outage_started_epoch=$(date -u +%s)
docker compose --profile browser stop --timeout 20 browser >/dev/null
if browser_ready; then
  echo "browser remained reachable during outage drill" >&2
  exit 1
fi

"$browser_session" start >/dev/null
browser_ready
downtime_seconds=$(( $(date -u +%s) - outage_started_epoch ))
"$browser_session" collect >"$after_state"
team_after=$(state_fingerprint <"$after_state")
[[ "$team_after" == "$team_before" ]]
image_after=$(docker inspect mova-fpl-browser-1 --format '{{.Image}}')
image_revision_after=$(docker inspect mova-fpl-browser-1 --format \
  '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
[[ "$image_after" == "$image_before" && "$image_revision_after" == "$revision" ]]
controls_after=$(controls_fingerprint)
[[ "$controls_after" == "$controls_before" ]]

# Restore the intentional on-demand service state before sealing evidence.
if [[ "$initial_running" -eq 0 ]]; then
  "$browser_session" stop >/dev/null
  ! browser_running
else
  "$browser_session" start >/dev/null
  browser_ready
fi

finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
host_path="$inbox/browser-recovery-${revision}-${started_epoch}.json"
python3 - "$host_path" "$started_at" "$finished_at" "$downtime_seconds" \
  "$revision" "$team_before" "$team_after" <<'PY'
import json
import os
import sys

path, started, finished, duration, revision, team_before, team_after = sys.argv[1:]
payload = {
    "schema": "mova-host-drill-v1", "scenario": "browser_recovery",
    "status": "pass", "started_at": started, "finished_at": finished,
    "downtime_seconds": int(duration), "revision": revision,
    "checks": {
        "browser_ready_before": True,
        "session_authenticated_before": True,
        "browser_unavailable_during": True,
        "browser_ready_after": True,
        "session_authenticated_after": True,
        "revision_unchanged": True,
        "team_state_unchanged": True,
        "controls_fail_closed": True,
        "initial_service_state_restored": True,
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

rm -f "$before_state" "$after_state"
/usr/local/bin/mova drill import-host --file "$host_path" --actor "$actor" \
  --reason "$reason" --scenario browser_recovery \
  --idempotency-key "$idempotency_key"

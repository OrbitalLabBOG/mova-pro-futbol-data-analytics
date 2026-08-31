#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}
actor=${1:?usage: reboot-recovery-prepare.sh ACTOR REASON IDEMPOTENCY_KEY}
reason=${2:?usage: reboot-recovery-prepare.sh ACTOR REASON IDEMPOTENCY_KEY}
idempotency_key=${3:?usage: reboot-recovery-prepare.sh ACTOR REASON IDEMPOTENCY_KEY}

set -a
source "$deploy_env"
set +a
cd "$repo_dir"

exec 9>/run/lock/mova-fpl-reboot-recovery.lock
flock -n 9 || { echo "another reboot recovery workflow is active" >&2; exit 75; }

set +e
existing=$(/usr/local/bin/mova drill host-status --scenario reboot_recovery \
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

data_root=${MOVA_DATA_ROOT:-/var/lib/mova-fpl}
runtime_root="$data_root/runtime"
pending="$runtime_root/reboot-recovery.pending.json"
install -d -m 0750 "$runtime_root"

if [[ -e "$pending" ]]; then
  set +e
  pending_result=$(python3 - "$pending" "$actor" "$reason" "$idempotency_key" <<'PY'
import json
import sys
import time

path, actor, reason, key = sys.argv[1:]
payload = json.load(open(path, encoding="utf-8"))
if payload.get("schema") != "mova-reboot-recovery-request-v1":
    raise SystemExit("invalid pending reboot recovery schema")
if int(payload.get("expires_epoch") or 0) < int(time.time()):
    print(json.dumps({"status": "expired", "prepared_at": payload["prepared_at"]}))
    raise SystemExit(3)
expected = {"actor": actor, "reason": reason, "idempotency_key": key}
if any(payload.get(name) != value for name, value in expected.items()):
    print("pending reboot recovery belongs to a different identity", file=sys.stderr)
    raise SystemExit(2)
print(json.dumps({
    "schema": "mova-reboot-recovery-preparation-v1",
    "status": "reused", "prepared_at": payload["prepared_at"],
    "revision": payload["revision"], "reboot_executed": False,
}, sort_keys=True))
PY
  )
  pending_rc=$?
  set -e
  if [[ "$pending_rc" -eq 0 ]]; then
    echo "$pending_result"
    exit 0
  fi
  if [[ "$pending_rc" -eq 3 ]]; then
    mv "$pending" "$runtime_root/reboot-recovery.expired.$(date -u +%s).json"
  else
    exit "$pending_rc"
  fi
fi

api_url="http://127.0.0.1:${MOVA_API_PORT:-8787}/readyz"
curl --fail --silent --show-error "$api_url" >/dev/null
/usr/local/bin/mova postgres verify >/dev/null

timers=(
  mova-fpl-tick.timer mova-fpl-watchdog.timer mova-fpl-private-state.timer
  mova-fpl-research.timer mova-fpl-collector.timer mova-fpl-analytics.timer
  mova-fpl-backup.timer mova-fpl-postgres-sync.timer
)
for unit in "${timers[@]}"; do
  [[ "$(systemctl is-active "$unit")" == "active" ]]
done

status_json=$(/usr/local/bin/mova status --json | tail -n 1)
safety_json=$(/usr/local/bin/mova safety | tail -n 1)
team_state_sha256=$(python3 -c 'import json,sys; p=json.load(sys.stdin); print(p["data"]["team_state"]["fingerprint"])' <<<"$status_json")
tick_job_id=$(python3 -c 'import json,sys; p=json.load(sys.stdin); print(p["operations"]["latest_tick"]["job_id"])' <<<"$status_json")
controls_sha256=$(python3 -c 'import hashlib,json,sys
p=json.load(sys.stdin); c=p.get("controls") or {}
expected={"action_level":"A0","browser_writes":False,"compliance_gate":"pending","kill_switch":True,"mode":"shadow"}
if c != expected: raise SystemExit("reboot drill requires fail-closed A0 controls")
print(hashlib.sha256(json.dumps(c,sort_keys=True,separators=(",",":")).encode()).hexdigest())' <<<"$safety_json")

backup_json=$(/usr/local/bin/mova backup --force --actor "$actor" \
  --reason "pre-reboot recovery drill: $reason" \
  --idempotency-key "reboot-pre-$idempotency_key" | tail -n 1)
backup_path=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])' <<<"$backup_json")
[[ -d "$backup_path" ]]
postgres_backup_path=$(deploy/bin/postgres-shadow-backup.sh)
[[ -d "$postgres_backup_path" ]]

revision=$(git rev-parse --short HEAD)
boot_id=$(cat /proc/sys/kernel/random/boot_id)
prepared_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
prepared_epoch=$(date -u +%s)
expires_epoch=$((prepared_epoch + 600))
expires_at=$(date -u -d "@$expires_epoch" +%Y-%m-%dT%H:%M:%SZ)
temporary=$(mktemp "$runtime_root/.reboot-recovery.XXXXXX")
python3 - "$temporary" "$actor" "$reason" "$idempotency_key" "$revision" \
  "$boot_id" "$prepared_at" "$prepared_epoch" "$expires_at" "$expires_epoch" \
  "$team_state_sha256" \
  "$controls_sha256" "$tick_job_id" "$backup_path" "$postgres_backup_path" <<'PY'
import json
import os
import sys

(path, actor, reason, key, revision, boot_id, prepared_at, prepared_epoch,
 expires_at, expires_epoch,
 team_hash, controls_hash, tick_job_id, backup_path, pg_backup_path) = sys.argv[1:]
payload = {
    "schema": "mova-reboot-recovery-request-v1", "actor": actor,
    "reason": reason, "idempotency_key": key, "revision": revision,
    "boot_id_before": boot_id, "prepared_at": prepared_at,
    "prepared_epoch": int(prepared_epoch), "expires_at": expires_at,
    "expires_epoch": int(expires_epoch), "team_state_sha256_before": team_hash,
    "controls_sha256_before": controls_hash, "tick_job_id_before": tick_job_id,
    "backup_path": backup_path, "postgres_backup_path": pg_backup_path,
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
PY
chmod 0640 "$temporary"
chown root:10001 "$temporary"
mv "$temporary" "$pending"

python3 - "$pending" <<'PY'
import json
import sys
p = json.load(open(sys.argv[1], encoding="utf-8"))
print(json.dumps({
    "schema": "mova-reboot-recovery-preparation-v1", "status": "prepared",
    "prepared_at": p["prepared_at"], "revision": p["revision"],
    "expires_at": p["expires_at"],
    "backup_prepared": True, "reboot_executed": False,
    "next_action": "obtain explicit authorization, then reboot the host",
}, sort_keys=True))
PY

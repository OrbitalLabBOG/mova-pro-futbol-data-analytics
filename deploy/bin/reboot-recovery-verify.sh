#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}
set -a
source "$deploy_env"
set +a
cd "$repo_dir"

data_root=${MOVA_DATA_ROOT:-/var/lib/mova-fpl}
runtime_root="$data_root/runtime"
pending="$runtime_root/reboot-recovery.pending.json"
[[ -f "$pending" ]] || exit 0

exec 9>/run/lock/mova-fpl-reboot-recovery.lock
flock -n 9 || exit 75

read_field() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]])' "$pending" "$1"
}

actor=$(read_field actor)
reason=$(read_field reason)
idempotency_key=$(read_field idempotency_key)
revision_before=$(read_field revision)
boot_id_before=$(read_field boot_id_before)
prepared_at=$(read_field prepared_at)
prepared_epoch=$(read_field prepared_epoch)
expires_epoch=$(read_field expires_epoch)
team_before=$(read_field team_state_sha256_before)
controls_before=$(read_field controls_sha256_before)
tick_before=$(read_field tick_job_id_before)
backup_path=$(read_field backup_path)
postgres_backup_path=$(read_field postgres_backup_path)

boot_id_after=$(cat /proc/sys/kernel/random/boot_id)
[[ "$boot_id_after" != "$boot_id_before" ]] || exit 75
boot_started_epoch=$(awk '$1=="btime" {print $2}' /proc/stat)
if (( boot_started_epoch > expires_epoch )); then
  expired="$runtime_root/reboot-recovery.expired.$(date -u +%s).json"
  mv "$pending" "$expired"
  echo '{"schema":"mova-reboot-recovery-verification-v1","status":"expired","reason":"reboot_started_after_preparation_ttl"}'
  exit 0
fi
revision_after=$(git rev-parse --short HEAD)
[[ "$revision_after" == "$revision_before" ]]
[[ -d "$backup_path" && -d "$postgres_backup_path" ]]

api_url="http://127.0.0.1:${MOVA_API_PORT:-8787}/readyz"
stack_ready=0
for _attempt in $(seq 1 150); do
  if curl -fsS --max-time 2 "$api_url" >/dev/null 2>&1 \
      && /usr/local/bin/mova postgres verify >/dev/null 2>&1; then
    stack_ready=1
    break
  fi
  sleep 2
done
[[ "$stack_ready" -eq 1 ]]

timers=(
  mova-fpl-tick.timer mova-fpl-watchdog.timer mova-fpl-private-state.timer
  mova-fpl-research.timer mova-fpl-collector.timer mova-fpl-analytics.timer
  mova-fpl-backup.timer mova-fpl-postgres-sync.timer
)
for unit in "${timers[@]}"; do
  [[ "$(systemctl is-active "$unit")" == "active" ]]
done

scheduler_resumed=0
status_json=""
for _attempt in $(seq 1 240); do
  status_json=$(/usr/local/bin/mova status --json | tail -n 1)
  tick_after=$(python3 -c 'import json,sys; p=json.load(sys.stdin); print(p["operations"]["latest_tick"]["job_id"])' <<<"$status_json")
  tick_status=$(python3 -c 'import json,sys; p=json.load(sys.stdin); print(p["operations"]["latest_tick"]["status"])' <<<"$status_json")
  if [[ "$tick_after" != "$tick_before" && "$tick_status" == "completed" ]]; then
    scheduler_resumed=1
    break
  fi
  sleep 2
done
[[ "$scheduler_resumed" -eq 1 ]]

team_after=$(python3 -c 'import json,sys; p=json.load(sys.stdin); print(p["data"]["team_state"]["fingerprint"])' <<<"$status_json")
[[ "$team_after" == "$team_before" ]]
safety_json=$(/usr/local/bin/mova safety | tail -n 1)
controls_after=$(python3 -c 'import hashlib,json,sys
p=json.load(sys.stdin); c=p.get("controls") or {}
expected={"action_level":"A0","browser_writes":False,"compliance_gate":"pending","kill_switch":True,"mode":"shadow"}
if c != expected: raise SystemExit("controls no longer fail closed")
print(hashlib.sha256(json.dumps(c,sort_keys=True,separators=(",",":")).encode()).hexdigest())' <<<"$safety_json")
[[ "$controls_after" == "$controls_before" ]]

doctor_json=$(/usr/local/bin/mova doctor --json --no-network | tail -n 1)
python3 -c 'import json,sys
p=json.load(sys.stdin)
if int((p.get("summary") or {}).get("required_failures") or 0): raise SystemExit(1)' <<<"$doctor_json"

ops_db="$data_root/db/ops.db"
idempotency_unique=$(docker compose --profile jobs run --rm --no-deps -T --entrypoint python \
  worker - "$ops_db" <<'PY'
import sqlite3
import sys
connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
try:
    quick = connection.execute("PRAGMA quick_check").fetchone()[0]
    duplicates = connection.execute(
        "SELECT COUNT(*) FROM (SELECT idempotency_key FROM job_runs "
        "GROUP BY idempotency_key HAVING COUNT(*)>1)"
    ).fetchone()[0]
finally:
    connection.close()
print("pass" if quick == "ok" and duplicates == 0 else "fail")
PY
)
[[ "$idempotency_unique" == "pass" ]]

finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
finished_epoch=$(date -u +%s)
downtime_seconds=$((finished_epoch - prepared_epoch))
(( downtime_seconds >= 0 && downtime_seconds <= 1200 ))

inbox="$data_root/artifacts/host-drills/inbox"
imported="$data_root/artifacts/host-drills/imported"
install -d -m 0750 -o 10001 -g 10001 "$inbox" "$imported"
host_path="$inbox/reboot-recovery-${revision_after}-${finished_epoch}.json"
python3 - "$host_path" "$prepared_at" "$finished_at" "$downtime_seconds" \
  "$revision_after" "$team_before" "$team_after" <<'PY'
import json
import os
import sys

path, started, finished, duration, revision, before, after = sys.argv[1:]
payload = {
    "schema": "mova-host-drill-v1", "scenario": "reboot_recovery",
    "status": "pass", "started_at": started, "finished_at": finished,
    "downtime_seconds": int(duration), "revision": revision,
    "checks": {
        "boot_id_changed": True, "stack_ready_after": True,
        "timers_active_after": True, "scheduler_resumed": True,
        "sqlite_integrity_after": True, "postgres_parity_after": True,
        "revision_unchanged": True, "controls_fail_closed": True,
        "team_state_unchanged": True, "idempotency_unique": True,
        "backup_prepared": True,
    },
    "team_state_sha256_before": before, "team_state_sha256_after": after,
    "fpl_state_mutated": False,
}
with open(path, "x", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
PY
chown 10001:10001 "$host_path"
chmod 0640 "$host_path"

/usr/local/bin/mova drill import-host --file "$host_path" --scenario reboot_recovery \
  --actor "$actor" --reason "$reason" --idempotency-key "$idempotency_key"
completed="$runtime_root/reboot-recovery.completed.$finished_epoch.json"
mv "$pending" "$completed"
chmod 0640 "$completed"

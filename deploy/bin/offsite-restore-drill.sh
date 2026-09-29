#!/usr/bin/env bash
set -euo pipefail

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}
backup_root=${MOVA_BACKUP_ROOT:-/opt/orbital/backups/mova-fpl}
actor=${1:?usage: offsite-restore-drill.sh ACTOR REASON IDEMPOTENCY_KEY}
reason=${2:?usage: offsite-restore-drill.sh ACTOR REASON IDEMPOTENCY_KEY}
idempotency_key=${3:?usage: offsite-restore-drill.sh ACTOR REASON IDEMPOTENCY_KEY}

[[ $(id -u) -eq 0 ]] || { echo "offsite restore drill must run as root" >&2; exit 2; }
[[ -r "$deploy_env" ]] && { set -a; source "$deploy_env"; set +a; }
backup_root=${MOVA_BACKUP_ROOT:-$backup_root}
cd "$repo_dir"
exec {drill_fd}>/run/lock/mova-fpl-offsite-restore-drill.lock
flock -n "$drill_fd" || { echo "another offsite restore drill is running" >&2; exit 75; }

set +e
existing=$(/usr/local/bin/mova drill host-status --scenario offsite_restore \
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

mapfile -t credential_files < <(./deploy/bin/offsite-backup.sh --config-paths)
[[ ${#credential_files[@]} -eq 2 ]] || exit 5
export RESTIC_REPOSITORY_FILE=${credential_files[0]}
export RESTIC_PASSWORD_FILE=${credential_files[1]}

# The target is disposable and never points at a runtime or backup directory.
restore_parent=${MOVA_RESTORE_DRILL_ROOT:-/opt/orbital/restore-drills}
[[ "$restore_parent" == /opt/orbital/restore-drills ]]
install -d -m 0700 -o root -g root "$restore_parent"
work_dir=$(mktemp -d "$restore_parent/offsite.XXXXXXXX")
cleanup() {
  rm -rf -- "$work_dir"
  unset RESTIC_REPOSITORY_FILE RESTIC_PASSWORD_FILE
}
trap cleanup EXIT HUP INT TERM

started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
started_epoch=$(date -u +%s)
revision=$(git rev-parse --short HEAD)
image_before=$(docker inspect mova-fpl-api-1 --format '{{.Image}}')
controls_before=$(/usr/local/bin/mova safety | tail -n 1 | python3 -c \
  'import json,sys; print(json.dumps(json.load(sys.stdin)["controls"], sort_keys=True))')
curl --fail --silent --show-error "http://127.0.0.1:${MOVA_API_PORT:-8787}/readyz" >/dev/null

restic snapshots --json --tag mova-fpl > "$work_dir/snapshots.json"
mapfile -t selection < <(python3 -m mova_fpl.ops.offsite_restore select \
  "$work_dir/snapshots.json" "$backup_root")
[[ ${#selection[@]} -eq 3 ]]
snapshot_id=${selection[0]}
sqlite_stamp=${selection[1]}
postgres_stamp=${selection[2]}
restic restore "$snapshot_id" --target "$work_dir/restore" --quiet
mapfile -t restored < <(python3 -m mova_fpl.ops.offsite_restore verify \
  "$work_dir/restore" "$backup_root" "$sqlite_stamp" "$postgres_stamp")
[[ ${#restored[@]} -eq 2 ]]
chgrp -R 10001 "$work_dir"
chmod 0750 "$work_dir"
find "$work_dir/restore" -type d -exec chmod g+rx {} +
find "$work_dir/restore" -type f -exec chmod g+r {} +

./deploy/bin/restore-drill.sh "${restored[0]}" >/dev/null
./deploy/bin/postgres-shadow-restore-drill.sh "${restored[1]}" >/dev/null

image_after=$(docker inspect mova-fpl-api-1 --format '{{.Image}}')
controls_after=$(/usr/local/bin/mova safety | tail -n 1 | python3 -c \
  'import json,sys; print(json.dumps(json.load(sys.stdin)["controls"], sort_keys=True))')
[[ "$image_after" == "$image_before" && "$controls_after" == "$controls_before" ]]
curl --fail --silent --show-error "http://127.0.0.1:${MOVA_API_PORT:-8787}/readyz" >/dev/null

rm -rf -- "$work_dir"
[[ ! -e "$work_dir" ]]
trap - EXIT HUP INT TERM
unset RESTIC_REPOSITORY_FILE RESTIC_PASSWORD_FILE
finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
duration=$(( $(date -u +%s) - started_epoch ))
[[ $duration -le 1800 ]]
inbox="${MOVA_DATA_ROOT:-/var/lib/mova-fpl}/artifacts/host-drills/inbox"
install -d -m 0750 -o 10001 -g 10001 "$inbox"
host_path="$inbox/offsite-restore-${revision}-${started_epoch}.json"
python3 - "$host_path" "$started_at" "$finished_at" "$duration" "$revision" \
  "$snapshot_id" <<'PY'
import json
import os
import sys

path, started, finished, duration, revision, snapshot_id = sys.argv[1:]
payload = {
    "schema": "mova-host-drill-v1", "scenario": "offsite_restore",
    "status": "pass", "started_at": started, "finished_at": finished,
    "downtime_seconds": 0, "elapsed_seconds": int(duration), "revision": revision,
    "checks": {key: True for key in (
        "encrypted_backup_present", "remote_snapshot_downloaded",
        "manifest_verified", "sqlite_restore_passed", "postgres_restore_passed",
        "artifacts_hashes_match", "credentials_not_persisted", "runtime_unchanged",
    )},
    "snapshot_id_prefix": snapshot_id[:12],
    "fpl_state_mutated": False,
}
temporary = path + ".tmp"
with open(temporary, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(temporary, 0o640)
os.chown(temporary, 10001, 10001)
os.replace(temporary, path)
PY
/usr/local/bin/mova drill import-host --file "$host_path" --actor "$actor" \
  --reason "$reason" --scenario offsite_restore \
  --idempotency-key "$idempotency_key"

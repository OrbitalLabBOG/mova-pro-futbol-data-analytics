#!/usr/bin/env bash
set -euo pipefail

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}
config_file=${MOVA_OFFSITE_BACKUP_CONFIG:-/etc/mova-fpl/offsite-backup.json}
backup_root=${MOVA_BACKUP_ROOT:-/opt/orbital/backups/mova-fpl}

[[ $(id -u) -eq 0 ]] || { echo "off-host backup must run as root" >&2; exit 2; }
command -v restic >/dev/null || { echo "restic is not installed" >&2; exit 3; }
[[ -r "$config_file" && ! -L "$config_file" ]] || {
  echo "off-host backup config is absent or unsafe" >&2; exit 4;
}

mapfile -t credential_files < <(python3 - "$config_file" <<'PY'
import json
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = {"schema", "enabled", "provider", "owner", "repository_file", "password_file"}
path_info = path.lstat()
if (stat.S_ISLNK(path_info.st_mode) or not stat.S_ISREG(path_info.st_mode)
        or path_info.st_uid != 0 or path_info.st_mode & 0o077 or path_info.st_size > 16384):
    raise SystemExit("unsafe off-host config")
payload = json.loads(path.read_text(encoding="utf-8"))
if not isinstance(payload, dict) or set(payload) != expected:
    raise SystemExit("invalid off-host config schema")
if payload["schema"] != "mova-offsite-backup-v1" or payload["enabled"] is not True:
    raise SystemExit("off-host backup is not explicitly enabled")
if payload["provider"] != "restic" or not payload["owner"]:
    raise SystemExit("invalid off-host provider or owner")
for key in ("repository_file", "password_file"):
    candidate = Path(payload[key])
    info = candidate.lstat()
    if (not candidate.is_absolute() or candidate.parent != Path("/etc/mova-fpl")
            or stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 4096):
        raise SystemExit(f"unsafe {key}")
repository = Path(payload["repository_file"]).read_bytes().strip().lower()
if not repository.startswith((b"azure:", b"b2:", b"gs:", b"rclone:", b"rest:",
                              b"s3:", b"sftp:", b"swift:")):
    raise SystemExit("repository is not an allowlisted external destination")
print(payload["repository_file"])
print(payload["password_file"])
PY
)
[[ ${#credential_files[@]} -eq 2 ]] || { echo "invalid off-host credentials" >&2; exit 5; }

if [[ -r "$deploy_env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$deploy_env"
  set +a
fi

cd "$repo_dir"
./deploy/bin/backup-all.sh >/dev/null
./deploy/bin/postgres-shadow-backup.sh >/dev/null

sqlite_backup=$(find "$backup_root" -mindepth 1 -maxdepth 1 -type d \
  -name '20????????T??????Z' -printf '%f\n' | sort | tail -1)
postgres_backup=$(find "$backup_root/postgres" -mindepth 1 -maxdepth 1 -type d \
  -name '20????????T??????Z' -printf '%f\n' | sort | tail -1)
[[ -n "$sqlite_backup" && -n "$postgres_backup" ]] || {
  echo "verified local backup set is incomplete" >&2; exit 6;
}

export RESTIC_REPOSITORY_FILE=${credential_files[0]}
export RESTIC_PASSWORD_FILE=${credential_files[1]}
trap 'unset RESTIC_REPOSITORY_FILE RESTIC_PASSWORD_FILE' EXIT HUP INT TERM
restic backup --quiet --tag mova-fpl --tag operational-databases \
  "$backup_root/$sqlite_backup" "$backup_root/postgres/$postgres_backup"
restic snapshots --json --latest 1 --tag mova-fpl >/dev/null
echo "encrypted off-host backup completed"

#!/usr/bin/env bash
# Metadata-only check: no restore, credential export, or runtime mutation.
set -euo pipefail
umask 077
[[ $(id -u) -eq 0 ]] || exit 2
repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
if [[ -r /etc/mova-fpl/deploy.env ]]; then
  set -a
  source /etc/mova-fpl/deploy.env
  set +a
fi
mapfile -t creds < <("$repo_dir/deploy/bin/offsite-backup.sh" --config-paths)
[[ ${#creds[@]} -eq 2 ]] || exit 2
export RESTIC_REPOSITORY_FILE=${creds[0]} RESTIC_PASSWORD_FILE=${creds[1]}
work=$(mktemp -d /run/mova-dr-status.XXXXXXXX)
trap 'rm -rf -- "$work"; unset RESTIC_REPOSITORY_FILE RESTIC_PASSWORD_FILE' EXIT
restic snapshots --json --tag mova-fpl > "$work/snapshots.json" 2>/dev/null
revision=$(git -C "$repo_dir" rev-parse HEAD)
script_dir=$(cd -- "$(dirname -- "$0")" && pwd)
set +e
python3 "$script_dir/dr-preflight.py" --repo "$repo_dir" \
  --expected-revision "$revision" --snapshots "$work/snapshots.json" > "$work/report.json"
rc=$?
set -e
# Missing/invalid report never replaces the previous observation.
python3 - "$work/report.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
if p.get('schema')!='mova-dr-preflight-v1': raise SystemExit(2)
PY
report_root=/var/lib/mova-dr
[[ ! -L "$report_root" ]]
install -d -m 0750 -o root -g 10001 "$report_root"
[[ -d "$report_root" && ! -L "$report_root" ]]
[[ ! -L "$report_root/status.json" ]]
install -m 0640 -o root -g 10001 "$work/report.json" "$report_root/status.new.json"
mv "$report_root/status.new.json" "$report_root/status.json"
cat "$report_root/status.json"
exit "$rc"

#!/usr/bin/env bash
set -euo pipefail

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}
runtime_env=${MOVA_ENV_FILE:-/etc/mova-fpl/runtime.env}
keep_browser=${MOVA_BROWSER_KEEP_RUNNING:-0}
lock_file=${MOVA_PRIVATE_STATE_LOCK_FILE:-/run/lock/mova-fpl-private-state.lock}
force=0
trigger=scheduled
if [[ "${1:-}" == "--force" ]]; then
  force=1
  trigger=forced
elif [[ $# -gt 0 ]]; then
  echo "usage: $0 [--force]" >&2
  exit 2
fi

for env_file in "$deploy_env" "$runtime_env"; do
  if [[ -r "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
done

lock_file=${MOVA_PRIVATE_STATE_LOCK_FILE:-$lock_file}
mkdir -p "$(dirname "$lock_file")"
exec 9>"$lock_file"
if ! flock -n 9; then
  printf '%s\n' '{"status":"skipped","reason":"private_state_lock_busy"}'
  exit 0
fi

cd "$repo_dir"
if [[ "$force" != "1" ]]; then
  set +e
  schedule_output=$(docker compose --profile jobs run --rm --no-deps -T worker \
    python -m mova_fpl.ops.cli private-state-due)
  schedule_status=$?
  set -e
  printf '%s\n' "$schedule_output"
  if [[ $schedule_status -eq 75 ]]; then
    exit 0
  elif [[ $schedule_status -ne 0 ]]; then
    exit "$schedule_status"
  fi
else
  printf '%s\n' '{"due":true,"reason":"forced_pre_or_post_action"}'
fi

private_input=$(mktemp /var/lib/mova-fpl/private-team-state.XXXXXX.json)
chmod 0600 "$private_input"
cleanup() {
  rm -f "$private_input"
  if [[ "$keep_browser" != "1" ]]; then
    "$repo_dir/deploy/bin/browser-session.sh" stop >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

collected=0
for attempt in 1 2 3; do
  if "$repo_dir/deploy/bin/browser-session.sh" collect >"$private_input" \
    && python3 - "$private_input" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
if payload.get("schema") != "mova-fpl-private-team-state-v1":
    raise SystemExit("unexpected private team-state schema")
if len(payload.get("picks") or ()) != 15:
    raise SystemExit("private team-state does not contain 15 picks")
PY
  then
    collected=1
    break
  fi
  printf 'private team-state capture attempt %s/3 failed\n' "$attempt" >&2
  sleep 2
done
if [[ "$collected" != "1" ]]; then
  echo "private team-state capture failed after 3 attempts" >&2
  exit 1
fi
docker compose --profile jobs run --rm --no-deps -T worker \
  python -m mova_fpl.ops.cli ingest-team-state --file - \
  --trigger "$trigger" <"$private_input"

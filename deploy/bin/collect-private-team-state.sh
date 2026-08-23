#!/usr/bin/env bash
set -euo pipefail

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}
runtime_env=${MOVA_ENV_FILE:-/etc/mova-fpl/runtime.env}
keep_browser=${MOVA_BROWSER_KEEP_RUNNING:-0}

for env_file in "$deploy_env" "$runtime_env"; do
  if [[ -r "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
done

cd "$repo_dir"
private_input=$(mktemp /var/lib/mova-fpl/private-team-state.XXXXXX.json)
chmod 0600 "$private_input"
cleanup() {
  rm -f "$private_input"
  if [[ "$keep_browser" != "1" ]]; then
    "$repo_dir/deploy/bin/browser-session.sh" stop >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

"$repo_dir/deploy/bin/browser-session.sh" collect >"$private_input"
docker compose --profile jobs run --rm --no-deps -T worker \
  python -m mova_fpl.ops.cli ingest-team-state --file - <"$private_input"

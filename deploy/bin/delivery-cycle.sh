#!/usr/bin/env bash
# Host dispatcher. The engine never receives Docker/CDP access.
set -euo pipefail
umask 077
repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
mova_bin=${MOVA_BIN:-/usr/local/bin/mova}
browser=${MOVA_BROWSER_SESSION_BIN:-$repo_dir/deploy/bin/browser-session.sh}
driver=${MOVA_EXECUTE_R2_BIN:-$repo_dir/deploy/bin/execute-r2-browser.sh}
run_root=${MOVA_RUN_ROOT:-/run}
cd "$repo_dir"
exec 7>"$run_root/lock/mova-fpl-delivery.lock"
flock -n 7 || exit 75
actor=mova-delivery-timer
reason='scheduled bounded lineup delivery'
proof_args=()
if [[ ${1:-} == --proof && $# == 1 ]]; then
  proof_args=(--proof)
  reason='owner-authorized expiring reversible live save proof'
elif [[ $# != 0 ]]; then
  echo 'usage: delivery-cycle.sh [--proof]' >&2; exit 2
fi
field() { python3 -c 'import json,sys; print(json.load(sys.stdin).get(sys.argv[1],""))' "$1"; }
due=$("$mova_bin" execute dispatch --check-only "${proof_args[@]}" --actor "$actor" --reason "$reason" | tail -n 1)
printf '%s\n' "$due"
[[ $(printf '%s' "$due" | field status) == due ]] || exit 0
refresh_key=$(printf '%s' "$due" | field refresh_key)
exec 9>"$run_root/lock/mova-fpl-private-state.lock"
flock -n 9 || exit 75
exec 8>"$run_root/lock/mova-fpl-capacity.lock"
flock -n 8 || exit 75
# Mount-visible input uses stdin; no auth/session material leaves the browser.
input=$(mktemp "$run_root/mova-delivery.XXXXXX")
trap 'rm -f "$input"' EXIT
timeout --kill-after=5s 120s "$browser" collect > "$input"
"$mova_bin" ingest-team-state --file - --trigger scheduled < "$input"
"$mova_bin" tick --force --actor "$actor" --reason "$reason" --idempotency-key "$refresh_key"
dispatch=$("$mova_bin" execute dispatch "${proof_args[@]}" --actor "$actor" --reason "$reason" | tail -n 1)
printf '%s\n' "$dispatch"
[[ $(printf '%s' "$dispatch" | field status) == prepared ]] || exit 0
execution_id=$(printf '%s' "$dispatch" | field execution_id)
[[ "$execution_id" =~ ^execution_[a-zA-Z0-9_-]+$ ]] || exit 2
# Driver owns its own locks and revalidates state/authority before crossing begin.
flock -u 8
flock -u 9
exec 8>&-
exec 9>&-
"$driver" --execution-id "$execution_id" --actor "$actor" --reason "$reason" --lease-seconds 600

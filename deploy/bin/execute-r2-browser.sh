#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
mova_bin=${MOVA_BIN:-mova}
browser_session=${MOVA_BROWSER_SESSION_BIN:-$repo_dir/deploy/bin/browser-session.sh}
browser_driver=${MOVA_BROWSER_R2_DRIVER:-$repo_dir/deploy/bin/browser-r2-driver.py}
run_root=${MOVA_RUN_ROOT:-/run}

execution_id=""
actor=""
reason=""
lease_seconds=300
while [[ $# -gt 0 ]]; do
  case "$1" in
    --execution-id) execution_id=${2:-}; shift 2 ;;
    --actor) actor=${2:-}; shift 2 ;;
    --reason) reason=${2:-}; shift 2 ;;
    --lease-seconds) lease_seconds=${2:-}; shift 2 ;;
    -h|--help)
      echo "usage: $0 --execution-id execution_... --actor NAME --reason TEXT [--lease-seconds 30..600]"
      exit 0
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [[ ! "$execution_id" =~ ^execution_[a-zA-Z0-9_-]+$ ]]; then
  echo "invalid execution id" >&2
  exit 2
fi
if [[ -z "$actor" || -z "$reason" || ! "$lease_seconds" =~ ^[0-9]+$ ]] \
  || (( lease_seconds < 30 || lease_seconds > 600 )); then
  echo "actor, reason and lease 30..600 are required" >&2
  exit 2
fi

cd "$repo_dir"
work_dir=$(mktemp -d "$run_root/mova-fpl-r2.XXXXXX")
pre_state=$work_dir/pre-state.json
dom_probe=$work_dir/dom-probe.json
ui_plan=$work_dir/ui-plan.json
post_state=$work_dir/post-state.json
claim_token=""
attempt_phase="unclaimed"
terminal=0
failure_code="HOST_DRIVER_FAILED"
lease_expires_at=""

bounded() {
  local cap=$1 seconds
  shift
  seconds=$(python3 - "$cap" "$lease_expires_at" <<'PY'
from datetime import datetime, timezone
import sys
cap = int(sys.argv[1])
if sys.argv[2]:
    expiry = datetime.fromisoformat(sys.argv[2].replace('Z', '+00:00'))
    if expiry.tzinfo is None: raise SystemExit(2)
    cap = min(cap, int((expiry-datetime.now(timezone.utc)).total_seconds())-4)
if cap <= 0: raise SystemExit(2)
print(cap)
PY
) || { echo "execution clock expired" >&2; return 2; }
  timeout --signal=TERM --kill-after=3s "${seconds}s" "$@"
}

emit() {
  python3 - "$1" "$execution_id" <<'PY'
import json
import sys
print(json.dumps({"event": sys.argv[1], "execution_id": sys.argv[2]}), flush=True)
PY
}

json_field() {
  python3 -c 'import json, sys
try:
    payload = json.load(sys.stdin)
    value = payload.get(sys.argv[1])
except (ValueError, AttributeError):
    print("invalid execution response", file=sys.stderr)
    raise SystemExit(2)
if value is None: raise SystemExit(2)
print(value)' "$1"
}

cleanup() {
  local status=$?
  trap - EXIT HUP INT TERM
  set +e
  if [[ $status -ne 0 && $terminal -eq 0 && -n "$claim_token" ]]; then
    if [[ "$attempt_phase" == "claimed" ]]; then
      printf '%s' "$claim_token" | timeout --kill-after=3s 15s "$mova_bin" execute fail \
        --execution-id "$execution_id" --classification failed \
        --error-code "$failure_code" --error-detail "host driver stopped before apply" \
        --actor "$actor" --reason "$reason" --claim-token-stdin >/dev/null 2>&1
    elif [[ "$attempt_phase" == "applying" || "$attempt_phase" == "begin_requested" ]]; then
      printf '%s' "$claim_token" | timeout --kill-after=3s 15s "$mova_bin" execute fail \
        --execution-id "$execution_id" --classification ambiguous \
        --error-code "$failure_code" --error-detail "host driver stopped after apply boundary" \
        --actor "$actor" --reason "$reason" --claim-token-stdin >/dev/null 2>&1
      # A lost begin response may mean either claimed or applying. Each API
      # transition checks its source state/token atomically; never issue Save.
      if [[ $? -ne 0 && "$attempt_phase" == "begin_requested" ]]; then
        printf '%s' "$claim_token" | timeout --kill-after=3s 15s "$mova_bin" execute fail \
          --execution-id "$execution_id" --classification failed \
          --error-code "$failure_code" --error-detail "begin response lost before driver dispatch" \
          --actor "$actor" --reason "$reason" --claim-token-stdin >/dev/null 2>&1
      fi
    fi
  fi
  timeout --kill-after=3s 15s "$browser_session" stop >/dev/null 2>&1 || true
  rm -f "$pre_state" "$dom_probe" "$ui_plan" "$post_state"
  rmdir "$work_dir" >/dev/null 2>&1 || true
  claim_token=""
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

emit browser_execution_claim_started
claim_payload=$(bounded 30 "$mova_bin" execute claim \
  --execution-id "$execution_id" --actor "$actor" --reason "$reason" \
  --lease-seconds "$lease_seconds" | tail -n 1)
claim_token=$(printf '%s' "$claim_payload" | json_field claim_token)
claim_status=$(printf '%s' "$claim_payload" | json_field status)
if [[ "$claim_status" != "claimed" ]]; then
  terminal=1
  echo "execution claim did not reach claimed" >&2
  exit 2
fi
attempt_phase="claimed"
lease_expires_at=$(printf '%s' "$claim_payload" | json_field lease_expires_at)
emit browser_execution_claimed

failure_code="PRE_STATE_CAPTURE_FAILED"
bounded 45 "$browser_session" collect >"$pre_state"
failure_code="DOM_PROBE_FAILED"
bounded 90 "$browser_session" probe >"$dom_probe"
failure_code="UI_PLAN_BLOCKED"
bounded 30 "$mova_bin" execute ui-plan \
  --execution-id "$execution_id" --pre-state "$pre_state" --dom-probe "$dom_probe" \
  | tail -n 1 >"$ui_plan"
[[ $(json_field status <"$ui_plan") == "ready" ]]
bounded 30 python3 "$browser_driver" --ui-plan "$ui_plan" --validate-only >/dev/null
emit browser_ui_plan_validated

failure_code="BEGIN_FAILED"
attempt_phase="begin_requested"
set +e
begin_payload=$(printf '%s' "$claim_token" | bounded 30 "$mova_bin" execute begin \
  --execution-id "$execution_id" --pre-state "$pre_state" \
  --actor "$actor" --reason "$reason" --claim-token-stdin | tail -n 1)
begin_rc=$?
set -e
begin_status=$(printf '%s' "$begin_payload" | json_field status)
if [[ $begin_rc -ne 0 || "$begin_status" != "applying" ]]; then
  if [[ "$begin_status" == "blocked" ]]; then
    terminal=1
  fi
  echo "execution did not cross apply boundary" >&2
  exit 2
fi
attempt_phase="applying"
emit browser_apply_boundary_crossed

failure_code="BROWSER_R2_DRIVER_FAILED"
bounded 600 python3 "$browser_driver" --ui-plan "$ui_plan"
emit browser_ui_commit_completed

failure_code="POST_STATE_CAPTURE_FAILED"
bounded 30 "$browser_session" collect >"$post_state"
failure_code="POST_STATE_VERIFICATION_FAILED"
set +e
final_payload=$(printf '%s' "$claim_token" | timeout --kill-after=3s 15s "$mova_bin" execute finalize \
  --execution-id "$execution_id" --post-state "$post_state" \
  --actor "$actor" --reason "$reason" --claim-token-stdin | tail -n 1)
final_rc=$?
set -e
final_status=$(printf '%s' "$final_payload" | json_field status)
terminal=1
claim_token=""
printf '%s\n' "$final_payload"
if [[ $final_rc -ne 0 || "$final_status" != "verified" ]]; then
  exit 2
fi
emit browser_execution_verified

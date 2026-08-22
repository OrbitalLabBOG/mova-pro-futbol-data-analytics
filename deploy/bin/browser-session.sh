#!/usr/bin/env bash
set -euo pipefail

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
deploy_env=${MOVA_DEPLOY_ENV:-/etc/mova-fpl/deploy.env}
action=${1:-status}

cd "$repo_dir"
if [[ -r "$deploy_env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$deploy_env"
  set +a
fi

compose=(docker compose --profile browser)

start_browser() {
  "${compose[@]}" up -d browser
  for _ in $(seq 1 45); do
    if curl -fsS http://127.0.0.1:${MOVA_NOVNC_PORT:-6080}/vnc.html >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  "${compose[@]}" logs --tail=100 browser >&2
  echo "browser did not become ready" >&2
  return 1
}

case "$action" in
  start)
    start_browser
    "${compose[@]}" ps browser
    ;;
  login)
    start_browser
    "${compose[@]}" exec -T browser \
      agent-browser --headed --session mova-fpl batch --bail \
      'open https://fantasy.premierleague.com/' \
      'wait --load domcontentloaded' 'get url' 'get title'
    echo "Open a tunnel: ssh -N -L ${MOVA_NOVNC_PORT:-6080}:127.0.0.1:${MOVA_NOVNC_PORT:-6080} root@72.60.245.2"
    echo "Then visit http://127.0.0.1:${MOVA_NOVNC_PORT:-6080}/vnc.html and complete login/MFA manually."
    ;;
  read)
    "${compose[@]}" exec -T browser \
      agent-browser --headed --session mova-fpl batch --bail \
      'open https://fantasy.premierleague.com/en/my-team' \
      'wait --load domcontentloaded' 'get url' 'get title' 'snapshot -i'
    ;;
  status)
    "${compose[@]}" ps -a browser
    if curl -fsS http://127.0.0.1:${MOVA_NOVNC_PORT:-6080}/vnc.html >/dev/null 2>&1; then
      echo "noVNC=ready listener=127.0.0.1:${MOVA_NOVNC_PORT:-6080}"
    else
      echo "noVNC=stopped"
    fi
    ;;
  stop)
    "${compose[@]}" stop browser
    ;;
  *)
    echo "usage: $0 {start|login|read|status|stop}" >&2
    exit 2
    ;;
esac

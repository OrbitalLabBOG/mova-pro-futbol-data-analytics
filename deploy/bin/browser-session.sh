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
cdp_port=${MOVA_BROWSER_CDP_PORT:-9222}

start_browser() {
  "${compose[@]}" up -d browser
  for _ in $(seq 1 45); do
    if curl -fsS http://127.0.0.1:${MOVA_NOVNC_PORT:-6080}/vnc.html >/dev/null 2>&1 \
      && "${compose[@]}" exec -T browser \
        curl -fsS "http://127.0.0.1:${cdp_port}/json/version" >/dev/null 2>&1; then
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
      agent-browser --session mova-fpl --cdp "$cdp_port" batch --bail \
      'open https://fantasy.premierleague.com/' \
      'get url' 'get title'
    echo "Open a tunnel: ssh -N -L ${MOVA_NOVNC_PORT:-6080}:127.0.0.1:${MOVA_NOVNC_PORT:-6080} root@72.60.245.2"
    echo "Then visit http://127.0.0.1:${MOVA_NOVNC_PORT:-6080}/vnc.html and complete login/MFA manually."
    ;;
  read)
    "${compose[@]}" exec -T browser \
      agent-browser --session mova-fpl --cdp "$cdp_port" batch --bail \
      'open https://fantasy.premierleague.com/en/my-team' \
      'get url' 'get title'
    ;;
  collect)
    team_id=${MOVA_TEAM_ID:-3609854}
    if [[ ! "$team_id" =~ ^[1-9][0-9]*$ ]]; then
      echo "invalid MOVA_TEAM_ID" >&2
      exit 2
    fi
    start_browser
    "${compose[@]}" exec -T browser \
      agent-browser --session mova-fpl --cdp "$cdp_port" \
      open https://fantasy.premierleague.com/ >/dev/null
    "${compose[@]}" exec -T browser \
      agent-browser --session mova-fpl --cdp "$cdp_port" \
      wait --load domcontentloaded >/dev/null
    "${compose[@]}" exec -T browser \
      agent-browser --session mova-fpl --cdp "$cdp_port" \
      wait --fn "location.origin === 'https://fantasy.premierleague.com'" >/dev/null
    "${compose[@]}" exec -T browser sh -c \
      "sed 's/__MOVA_TEAM_ID__/$team_id/' /opt/mova/private-team-state.js | \
       agent-browser --session mova-fpl --cdp '$cdp_port' eval --stdin"
    ;;
  probe)
    team_id=${MOVA_TEAM_ID:-3609854}
    if [[ ! "$team_id" =~ ^[1-9][0-9]*$ ]]; then
      echo "invalid MOVA_TEAM_ID" >&2
      exit 2
    fi
    start_browser
    "${compose[@]}" exec -T browser \
      agent-browser --session mova-fpl --cdp "$cdp_port" \
      open https://fantasy.premierleague.com/en/my-team >/dev/null
    "${compose[@]}" exec -T browser \
      agent-browser --session mova-fpl --cdp "$cdp_port" \
      wait --load domcontentloaded >/dev/null
    "${compose[@]}" exec -T browser sh -c \
      "sed 's/__MOVA_TEAM_ID__/$team_id/' /opt/mova/pick-team-dom-probe.js | \
       agent-browser --session mova-fpl --cdp '$cdp_port' eval --stdin"
    ;;
  status)
    "${compose[@]}" ps -a browser
    if curl -fsS http://127.0.0.1:${MOVA_NOVNC_PORT:-6080}/vnc.html >/dev/null 2>&1; then
      if "${compose[@]}" exec -T browser \
        curl -fsS "http://127.0.0.1:${cdp_port}/json/version" >/dev/null 2>&1; then
        echo "noVNC=ready cdp=ready listeners=127.0.0.1:${MOVA_NOVNC_PORT:-6080},container:${cdp_port}"
      else
        echo "noVNC=ready cdp=stopped"
      fi
    else
      echo "noVNC=stopped"
    fi
    ;;
  stop)
    "${compose[@]}" stop browser
    ;;
  *)
    echo "usage: $0 {start|login|read|collect|probe|status|stop}" >&2
    exit 2
    ;;
esac

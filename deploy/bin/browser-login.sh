#!/usr/bin/env bash
set -euo pipefail

repo_dir=${MOVA_REPO_DIR:-/opt/orbital/services/mova-fpl}
cd "$repo_dir"
docker compose --profile browser up -d browser
docker compose --profile browser exec browser \
  agent-browser --session mova-fpl --profile /var/lib/mova-fpl/browser-profile --headed \
  open https://fantasy.premierleague.com/
echo "noVNC is bound to VPS loopback only. Open an SSH tunnel:"
echo "ssh -L 6080:127.0.0.1:6080 root@72.60.245.2"
echo "Then visit http://127.0.0.1:6080/vnc.html and complete login/MFA manually."

#!/usr/bin/env bash
set -euo pipefail

repo_dir=${1:-/opt/orbital/services/mova-fpl}
if [[ ! -f "$repo_dir/compose.yaml" ]]; then
  echo "missing compose.yaml under $repo_dir" >&2
  exit 2
fi

for unit in deploy/systemd/*.service deploy/systemd/*.timer; do
  sed "s|@@REPO_DIR@@|$repo_dir|g" "$unit" > "/etc/systemd/system/$(basename "$unit")"
done
systemctl daemon-reload
systemctl enable --now mova-fpl-stack.service
systemctl enable --now mova-fpl-tick.timer mova-fpl-private-state.timer \
  mova-fpl-backup.timer mova-fpl-watchdog.timer
systemctl list-timers --all 'mova-fpl-*' --no-pager

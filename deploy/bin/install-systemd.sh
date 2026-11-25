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
for dropin in deploy/systemd/*.timer.d/*.conf; do
  [[ -f "$dropin" ]] || continue
  target="/etc/systemd/system/$(basename "$(dirname "$dropin")")"
  install -d -m 0755 "$target"
  install -m 0644 "$dropin" "$target/$(basename "$dropin")"
done
systemctl daemon-reload
if [[ -e /usr/local/bin/mova && ! -L /usr/local/bin/mova ]]; then
  echo "/usr/local/bin/mova exists and is not a symlink; refusing to overwrite" >&2
  exit 3
fi
ln -sfn "$repo_dir/deploy/bin/mova" /usr/local/bin/mova
systemctl enable --now mova-fpl-stack.service
systemctl enable --now mova-fpl-tick.timer mova-fpl-private-state.timer \
  mova-fpl-backup.timer mova-fpl-watchdog.timer mova-fpl-collector.timer
systemctl enable --now mova-fpl-analytics.timer
systemctl enable --now mova-fpl-backup-retention.timer
systemctl enable --now mova-fpl-postgres-sync.timer
# ADR-021 (copiloto): la entrega programada y el research por timer quedan
# retirados. Los servicios se conservan como arranque manual/on-demand
# (mova-fpl-delivery.service falla cerrado con copilot_mode sin opt-in).
RETIRED_UNITS=(mova-fpl-delivery.timer mova-fpl-research.timer)
for unit in "${RETIRED_UNITS[@]}"; do
  systemctl disable --now "$unit" 2>/dev/null || true
  rm -f "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl reset-failed 'mova-fpl-delivery-proof-*' 2>/dev/null || true
systemctl enable mova-fpl-reboot-recovery.service
if systemctl is-active --quiet mova-fpl-offsite-backup.timer \
  && "$repo_dir/deploy/bin/offsite-backup.sh" --config-paths >/dev/null 2>&1; then
  systemctl enable --now mova-fpl-dr-status.timer
fi
systemctl list-timers --all 'mova-fpl-*' --no-pager

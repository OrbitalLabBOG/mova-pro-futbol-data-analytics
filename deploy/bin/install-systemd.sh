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
# ADR-022: el VPS solo garantiza colector, analytics, backup diario (con poda),
# offsite semanal y la pila Postgres/API. El resto del harness autonomo se retira.
systemctl enable --now mova-fpl-collector.timer mova-fpl-analytics.timer \
  mova-fpl-backup.timer
# ADR-021/022: tick, watchdog, dr-status, private-state, postgres-sync,
# backup-retention (poda integrada en el backup diario) y delivery quedan retirados.
# research es on-demand (sin timer); `mova postgres sync` y
# collect-private-team-state.sh --force siguen disponibles a demanda.
RETIRED_UNITS=(
  mova-fpl-tick.timer mova-fpl-tick.service
  mova-fpl-watchdog.timer mova-fpl-watchdog.service
  mova-fpl-dr-status.timer mova-fpl-dr-status.service
  mova-fpl-private-state.timer mova-fpl-private-state.service
  mova-fpl-postgres-sync.timer mova-fpl-postgres-sync.service
  mova-fpl-backup-retention.timer mova-fpl-backup-retention.service
  mova-fpl-delivery.timer mova-fpl-delivery.service
  mova-fpl-research.timer
)
for unit in "${RETIRED_UNITS[@]}"; do
  systemctl disable --now "$unit" 2>/dev/null || true
  rm -f "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl reset-failed 'mova-fpl-delivery-proof-*' 2>/dev/null || true
systemctl reset-failed "${RETIRED_UNITS[@]}" 2>/dev/null || true
systemctl enable mova-fpl-reboot-recovery.service
# Offsite (restic) sigue opt-in: se instala el timer semanal pero no se habilita aqui;
# habilitarlo a mano (habilitar el timer offsite) tras
# configurar offsite-backup.json.
systemctl list-timers --all 'mova-fpl-*' --no-pager

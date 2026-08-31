---
type: deployment-evidence
name: "HV1-02D — Encrypted off-host backup readiness"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, backup, restic, recovery, readiness, security]
status: verified-live-pending-destination
---

# HV1-02D — Encrypted off-host backup readiness

## Resultado

El riesgo de pérdida total del VPS ya no depende de una instrucción informal: existe un servicio
opt-in para copiar las bases operativas mediante restic, un probe sanitizado y dos gates separados
para configuración y restaurabilidad. No se eligió destino, no se instalaron credenciales y no
hubo llamadas externas; Q-04 continúa pendiente de autorización.

## Contrato implementado

- schema exacto `mova-offsite-backup-v1`, provider `restic` y owner explícito;
- configuración, descriptor de repositorio y password como archivos root-only bajo
  `/etc/mova-fpl`, sin symlinks ni tamaños anómalos;
- repositorio obligatoriamente remoto; una ruta local se rechaza;
- salida host sin URL/ruta/password, sólo fingerprint SHA-256 truncado y causas allowlisted;
- servicio systemd con lock, timeout de 30 minutos, `NoNewPrivileges` y ejecución root;
- backup SQLite/PostgreSQL verificado antes de transferir; browser-profile y `CODEX_HOME`
  excluidos;
- timer instalado pero no habilitado automáticamente;
- `OFF_HOST_BACKUP_CONFIGURED` exige configuración segura y timer activo;
- `OFF_HOST_RESTORE_PROVEN` exige un job completado con ocho checks: copia cifrada, descarga,
  manifest, restores SQLite/PostgreSQL, hashes, credenciales no persistidas y runtime intacto.

La evidencia importada usa el mismo contrato allowlisted/idempotente de host drills. No basta un
Markdown, una configuración presente o un snapshot remoto para cerrar el gate.

## Verificación

- commit funcional y checkout VPS: `a005ab9`;
- suite focal: 51 passed;
- suite completa: 1.211 passed, 1 skipped, 79 deselected;
- Bash, bytecode y diff checks válidos;
- pruebas de destino local, permisos amplios, ausencia de config, evidencia parcial, mutación y
  timeout >1.800 s rechazadas;
- unidad/timer renderizados en systemd, timer `disabled` e `inactive`;
- `/etc/mova-fpl/offsite-backup.json` ausente, por diseño;
- API `healthy`, doctor 23/23, watchdog `passed` sin alertas y safety `safe_to_wait`;
- controles: shadow/A0, kill switch activo, compliance pendiente y browser writes apagados;
- readiness vivo: 14 pass, 11 pending, 0 blocked, total 25;
- scorecard durability: 2 pass, 3 pending, 0 blocked;
- `offsite_restore`: `due`, exit 75, sin evidencia fabricada;
- backup pre SQLite `/opt/orbital/backups/mova-fpl/20260831T063619Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T063620Z`;
- backup post SQLite `/opt/orbital/backups/mova-fpl/20260831T063918Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T063918Z`.

## Pendiente autorizado

Para cerrar Q-04 se debe elegir proveedor/repositorio y owner, aprobar la transferencia de datos,
provisionar restic y secretos, ejecutar el primer backup, comprobar replay/cadencia y realizar un
restore aislado. Sólo entonces se habilita el timer y ambos gates pueden pasar. Esto no cambia el
writer SQLite, no promueve autonomía y no modifica la cuenta FPL.

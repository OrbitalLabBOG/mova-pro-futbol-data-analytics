---
type: deployment-evidence
name: "HV1-09B — Watchdog P0 y resilience drill"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, watchdog, resilience, alerts, idempotency]
status: verified-live
---

# HV1-09B — Watchdog P0 y resilience drill

## Hallazgo

El watchdog anterior detectaba un heartbeat ausente o vencido y terminaba non-zero, pero no abría
un incidente P0. En la rama `no_finished_tick` retornaba antes de despachar el outbox. Por tanto,
systemd veía el fallo pero el circuito de incidentes no cumplía WP-007/WP-008.

## Contrato corregido

- `mova watchdog` evalúa integridad, último tick, estado y edad;
- abre como máximo un P0 activo `Scheduler heartbeat unhealthy`;
- entrega alertas incluso en estado `down` y resuelve el P0 al recuperar heartbeat;
- devuelve `degraded`/non-zero si falla el sink o existe outbox `dead`;
- si SQLite no puede abrirse, emite un resultado sanitizado `control_plane_unavailable` a
  journald aunque no pueda persistirlo;
- `mova alerts retry` reabre sólo `dead` con actor/razón y rechaza repetir `sent/acknowledged`;
- `mova drill resilience` ensaya en SQLite efímero: missing tick, P0, delivery, segundo intento
  deduplicado, tick recuperado, resolución y continuidad de auditoría.

El drill no modifica el runtime (`runtime_mutated=false`). Su invocación real sí usa un job con
clave idempotente, resultado hash y métricas de checks.

## Gates preservados

No cambia `mode`, `action_level`, compliance, kill switch, browser, modelo ni decisiones. No
simula GWs para satisfacer readiness y no reemplaza un reboot/chaos drill vivo.

## Evidencia previa al rollout

- pruebas dirigidas iniciales: 16 pass;
- suite completa: `1084 passed, 1 skipped, 79 deselected`;
- `compileall` y `git diff --check`: pass.

La suite completa, Docker, el drill vivo, retry idempotente, doctor, PostgreSQL y backup se
anexarán sólo después de verificarlos en el VPS.

## Rollout vivo

El commit `a01b0a7` se construyó y desplegó en el VPS con tag y label iguales. Evidencia:

- predeploy backup: `/opt/orbital/backups/mova-fpl/20260831T012244Z`;
- smoke dentro de la imagen: seis checks true y `runtime_mutated=false`;
- replay con la misma clave: `status=reused`, mismo job
  `job_258060e4e6d74b50842f3183042337d3`;
- segundo drill vivo independiente: seis checks true, job
  `job_78df34f7522d40498d1fd18cb00e930c`;
- watchdog systemd real: heartbeat `ok`, cero claims/fallos/dead, exit exitoso;
- DB deliberadamente ausente en contenedor hermético: exit 1 y resultado sanitizado
  `control_plane_unavailable/OperationalError`, sin traceback en el contrato JSON;
- doctor: 22 pass, 0 warn, 0 fail; checkout/imagen `a01b0a7`;
- safety: `safe_to_wait`, cero incidentes y cero delivery pendiente;
- readiness: 9 pass, 6 pending temporales, 0 blocked; nivel A0;
- PostgreSQL import `pgimport_6b7e5a9c090642a1a7d6c6dc3f1eb24b`: paridad 54/54,
  cero fallos;
- postdeploy backup: `/opt/orbital/backups/mova-fpl/20260831T012733Z`.

No se creó un P0 falso en la DB productiva: el fallo y recuperación ocurrieron dentro de la base
efímera del drill. Los controles y el browser permanecieron intactos.

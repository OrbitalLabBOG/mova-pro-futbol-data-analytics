---
type: deployment-evidence
name: "HV1-09B — Watchdog P0 y resilience drill"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, watchdog, resilience, alerts, idempotency]
status: implemented-pending-live-rollout
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

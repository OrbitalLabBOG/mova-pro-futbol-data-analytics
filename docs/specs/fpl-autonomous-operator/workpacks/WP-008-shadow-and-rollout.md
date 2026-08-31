---
type: workpack
name: "WP-008 — Shadow, rehearsals y promoción de autonomía"
created: 2026-08-21
updated: 2026-08-31
tags: [mova, fpl, workpack, rollout, safety]
status: active-shadow
---

# WP-008 — Shadow, rehearsals y promoción de autonomía

## Objetivo

Validar el sistema end-to-end y promover niveles solo con evidencia, drills y aprobaciones.

## Dependencias

WP-001..007.

## Entregables

- scenario suite de deadline acelerado;
- chaos drills: reboot, API/DB/browser caídos, DOM drift, save ambiguo;
- reportes de 3 GWs/rehearsals shadow y supervised;
- checklist/gates G3–G6 y actas de aprobación;
- rollback y kill-switch drills;
- review mensual de seguridad y desempeño.

## Criterios de aceptación

- shadow completa cadena sin mutación ni jobs huérfanos;
- supervised produce evidencia exacta y acuse humano;
- guarded A1 cumple 3 GWs sin discrepancia antes de A2;
- A3 nunca se activa implícitamente;
- toda promoción y rollback queda auditada;
- P0 antes del deadline produce pausa y ruta humana;
- sistema conserva último equipo verificado bajo fallos combinados.

## Cierre

El workpack termina con una recomendación de nivel; no lo activa sin aprobación separada.

## Estado verificado

Ya existen readiness consolidado, rehearsals browser por capacidad, cutover/rollback de lectura,
restore drills e idempotencia de agentes. HV1-09B añade un escenario hermético repetible para
scheduler ausente, P0, delivery, deduplicación y recuperación. Continúan pendientes los escenarios
combinados API/DB/browser/DOM/save ambiguo, un reboot real, los ciclos independientes y las
aprobaciones; por ello el workpack permanece `active-shadow` y no recomienda promoción.

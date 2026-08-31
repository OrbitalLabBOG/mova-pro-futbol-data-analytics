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
scheduler ausente, P0, delivery, deduplicación y recuperación. HV1-09C verificó en producción una
caída real y recuperación del contenedor API en 7 s, con trap host, integridad posterior, import
allowlisted y replay sin segunda caída. HV1-09D verificó en producción la caída real de
PostgreSQL en 7 s con locks de writers,
continuidad SQLite/API, fingerprint del team state, paridad 54/54 y replay sin segunda caída. El
gate máquina conjunto `HOST_RECOVERY_DRILLS_PROVEN` pasa API+DB. HV1-09E implementa el rechazo
hermético y verificó en el VPS diez de diez checks para snapshots alterados, corruptos, tamaños,
nombres duplicados, traversal y symlinks; `SNAPSHOT_REJECTION_PROVEN` pasa. HV1-09F verificó once
de once checks de deriva DOM, pre-state cambiado, save ambiguo, P0 y no-retry;
`BROWSER_FAILURE_DRILL_PROVEN` pasa. HV1-09G recuperó una caída real del browser en 10 s,
con sesión/fingerprint intactos y estado on-demand restaurado; el gate host exige y pasa los tres
escenarios API+PostgreSQL+browser. Continúan pendientes escenarios combinados, un reboot real, los ciclos
independientes y las aprobaciones; por ello el workpack permanece `active-shadow` y no recomienda
promoción.

---
type: workpack
name: "WP-007 — Observabilidad, alertas y runbooks"
created: 2026-08-21
updated: 2026-08-31
tags: [mova, fpl, workpack, observability, runbooks]
status: active-shadow
---

# WP-007 — Observabilidad, alertas y runbooks

## Objetivo

Instrumentar la cadena completa y hacer visibles salud, deadline, fuentes, decisión,
ejecución, modelo e incidentes.

## Dependencias

WP-001/002; instrumentación incremental de WP-003..006.

## Entregables

- logs JSON, endpoint Prometheus-compatible y muestras de salud persistidas;
- propagación de IDs de correlación engine↔browser;
- dashboards Now/Decision/Operations/Learning/Audit;
- alert rules P0–P3, dedup, outbox y acuse;
- runbooks enlazados y post-GW automático;
- retention/cleanup con dry-run.

## Criterios de aceptación

- correlación continua desde tick hasta verify;
- scheduler muerto alerta por last success, no por ausencia manual;
- labels pasan audit de cardinalidad y secretos;
- cada P0/P1 se dispara en test y tiene acuse/cierre;
- dashboard permite saber en <60s si el equipo está seguro;
- telemetría caída no borra ledger ni habilita writes;
- cleanup nunca elimina evidencia decisiva o incidente abierto.

## Estado verificado

Logs JSON, correlation/job IDs, health persistido, Prometheus, doctor/readiness y runbooks ya
operan en shadow. El ledger agentic distingue consumo real, reservas activas y cargos estimados;
además detecta overruns por job y reservas huérfanas sin liberar presupuesto.

HV1-01B agregó `mova safety`, `/api/v1/safety` y la tarjeta de seguridad del dashboard; el
resultado reúne deadline, gates, frescura, incidentes y outbox en una sola lectura. P0 y P1 tienen
tests de entrega/fallo, el outbox recupera leases, reintenta y permite acuse auditado. `mova
maintenance cleanup` opera por defecto en dry-run y su allowlist sólo considera `.tmp`,
`.partial` y `.tmp-*`; symlinks y evidencia canónica quedan fuera. El workpack conserva
`active-shadow`: falta elegir y ensayar un canal externo de notificación si journald no basta para
la operación desatendida, y comprobar el flujo durante ciclos vivos.

HV1-09B endurece el scheduler muerto: `mova watchdog` abre/deduplica P0, intenta la entrega y
devuelve fallo también cuando el sink falla o existe outbox `dead`. `mova alerts retry` ofrece
recuperación explícita y auditada; reconocer un incidente también puede cerrar un evento `dead`
sin confundirlo con delivery. El rehearsal `mova drill resilience` verifica P0→delivery→dedup→
recovery en una base efímera y persiste sólo el job/resultado del ensayo en el ledger real.

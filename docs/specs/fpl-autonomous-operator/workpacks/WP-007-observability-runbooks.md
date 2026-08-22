---
type: workpack
name: "WP-007 — Observabilidad, alertas y runbooks"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, workpack, observability, runbooks]
status: proposed
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

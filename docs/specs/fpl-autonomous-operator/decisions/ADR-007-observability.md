---
type: decision
name: "ADR-007 — Observabilidad local primero"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, adr, observability]
status: proposed
---

# ADR-007 — Observabilidad local primero

## Decisión

Usar `ops.db` como ledger duradero, logs JSON, muestras locales de salud, dashboard privado,
endpoint Prometheus-compatible y watchdog systemd independiente. Propagar IDs de correlación
de punta a punta. No instalar inicialmente Prometheus, Grafana ni un collector OTel.

## Razón

El VPS no tiene un stack de métricas y ya hospeda once contenedores. El ledger y watchdog
cubren la falla más peligrosa —que el scheduler deje de correr— sin añadir una plataforma.
El endpoint estándar conserva una evolución futura sin acoplar el dominio.

## Consecuencias

La retención histórica inicial vive en `job_runs`, `job_steps`, `health_samples`,
`audit_events` e `incidents`. Si luego se incorpora Prometheus/Grafana, será un consumidor
del endpoint; el servicio seguirá operando si ese backend falla.

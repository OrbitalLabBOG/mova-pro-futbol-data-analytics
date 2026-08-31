---
type: deployment-evidence
name: "HV1-11 — Agent orchestration audit"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, agents, orchestration, idempotency, observability]
status: verified-live
---

# HV1-11 — Agent orchestration audit

## Objetivo

Poder entender y probar el orden completo del harness sin depender de logs dispersos, consumir
otra inferencia o confundir un bloqueo deliberado de policy con una falla del agente.

## Contrato implementado

- `mova harness workflow` y `GET /api/v1/orchestration`;
- nueve stages: observe, contextualize, research, propose/validate, deliberate, preflight,
  execute/verify, settle y review/learn;
- owners explícitos para Researcher, Strategist/Critic y componentes deterministas;
- detección de downstream sin dependencia, ejecución sin plan autorizado, review sin settlement,
  lección sin review y reserva agentic huérfana;
- outcomes `blocked` de envelope/preflight se consideran completos y producen
  `skipped_policy`, no falsos incidentes;
- métricas `mova_orchestration_*` con labels cerrados;
- gate `ORCHESTRATION_DRILL_PROVEN` en readiness;
- drill hermético de doce checks, sin DB externa, browser, red ni modelos.

## Evidencia viva

- implementación y producción `266849c`;
- suite completa: 1.160 passed, 1 skipped, 79 deselected;
- job `job_6e056e5b9e2342508f035e4e002bdd46`, 12/12 y output
  `a3ac68a7276dfa6f522731f6af1884caabfd351275e78886a7e923d3482e8478`;
- `external_calls=0`, `runtime_mutated=false`;
- replay exacto `reused`; razón diferente con la misma clave: exit 2 y conflicto sin segundo job;
- workflow GW3 `safe_to_wait`, cero violaciones: collector/context/research/propuesta/deliberación/
  preflight completos; executor omitido por policy; settlement y reviewer `not_due`;
- API y Prometheus coinciden con CLI; cero `mova_orchestration_dependency_violations`;
- readiness 14/20 pass, 6 pending, 0 blocked; operations 7/7 pass; autoridad A0 intacta;
- PostgreSQL `pgimport_9285f8ead1c14efe9367e88f3099ed15`: 55/55, paridad pass;
- doctor 22/22; safety `safe_to_wait`; browser autenticado leído y apagado al finalizar;
- backup previo `/opt/orbital/backups/mova-fpl/20260831T035153Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T035154Z`;
- backup posterior `/opt/orbital/backups/mova-fpl/20260831T035542Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T035542Z`.

## Límite explícito

El drill demuestra contrato e idempotencia, no calidad deportiva longitudinal. No suma GWs de
research, rehearsals browser ni imports PostgreSQL distintos; tampoco concede compliance,
habilita entrypoints o autoriza escrituras en FPL.

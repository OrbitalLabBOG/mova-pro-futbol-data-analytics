---
type: deployment-evidence
name: "HV1-10 — Harness quality and cost scorecard"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, harness, scorecard, cost, observability]
status: verified-live
---

# HV1-10 — Harness quality and cost scorecard

## Objetivo

Cerrar el gap entre métricas separadas de readiness, costo y mejora continua con una lectura única,
determinista y operable por ORBIX. El scorecard debía reutilizar policy existente, permanecer
read-only y no ampliar autonomía.

## Contrato implementado

- `mova harness scorecard` y `GET /api/v1/harness-scorecard`;
- schema `mova-harness-scorecard-v1`;
- dimensiones: operations, data/models, agentic decision, browser execution, durability,
  economics y continuous learning;
- calidad transparente como pass/pending/blocked de los 19 gates, sin puntuación opaca;
- costos GW/mes, reservas, overrun y reutilización semántica;
- deliberación terminal y memoria propuesta/evaluación/lección;
- métricas `mova_harness_*` con labels de cardinalidad acotada;
- `promotion_is_automatic=false`, A0 y browser writes sin cambios.

El presupuesto falla cerrado cuando GW/mes exceden límites o existe una reserva huérfana. Un
overrun individual ya consumado queda pending: exige revisión de prompt/budget, pero no bloquea
para siempre si los límites agregados siguen sanos.

## Evidencia

- implementación `9233743`; corrección semántica viva `884cb32`;
- suite completa final: `1146 passed, 1 skipped, 79 deselected`;
- suite dirigida: 17 pass; `git diff --check`: pass;
- backup previo: job `job_1e56aafb9e104e65aa03602c1893fb4b`, ruta
  `/opt/orbital/backups/mova-fpl/20260831T030639Z`;
- import PostgreSQL `pgimport_279e6f0f728a45bcbba756b57d58fb13`: 54/54, paridad pass;
- CLI/API/Prometheus vivos: schema correcto, siete dimensiones y métricas disponibles;
- scorecard final: 13 pass, 6 pending, 0 blocked sobre 19 gates; operations pass y las demás
  dimensiones pending; `readiness_pass_ratio=0.6842`, elegibilidad A0;
- costo GW3: 666.818/900.000 tokens y 16/20 usos; agosto: 1.019.605/3.000.000 y 18/60;
- hallazgo: Researcher usó 167.678 tokens, 7.678 sobre el límite individual;
- aprendizaje: tres propuestas, cero evaluaciones y cero lecciones persistidas;
- doctor: 22 pass, 0 warn, 0 fail; safety `safe_to_wait`;
- checkout, API y browser exactos en `884cb32`; sesión `/en/my-team` verificada; browser final
  `exited`;
- backup PostgreSQL posterior: `/opt/orbital/backups/mova-fpl/postgres/20260831T031201Z`;
- backup SQLite posterior forzado: job `job_ed44fc8f7fa449d89579c7b387498924`, ruta
  `/opt/orbital/backups/mova-fpl/20260831T031252Z`.

## Pendientes explícitos

El scorecard no resuelve evidencia temporal ni autoridad. Quedan pendientes settlement GW3,
calibración/rehearsals/ciclos multi-GW, revisión del overrun, primera lección completa, canal de
alertas externo, backup off-host, reboot real y aprobaciones de promoción/compliance.

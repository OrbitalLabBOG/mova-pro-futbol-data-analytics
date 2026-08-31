---
type: implementation-evidence
name: "MOVA FPL — HV1-06C idempotencia semántica agentic"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, agents, idempotency, cost, observability]
status: verified-local
---

# HV1-06C — idempotencia semántica agentic

## Problema observado

En GW3 se contabilizaron doce usos `strategy_critic`. El lifecycle era idempotente por
`envelope_id`, pero un nuevo manifest, batch o despliegue producía otro envelope aunque los
inputs deportivos y blockers fueran equivalentes. Cada revisión volvía a reservar presupuesto.

## Contrato implementado

- `semantic_input_sha256` incluye candidatos completos, checks, equipo, fase, research, memoria,
  plan y versiones de modelo.
- Provenance volátil sigue sellada en el request, pero queda fuera de la identidad semántica.
- La memoria excluye únicamente `as_of_at` y su hash derivado; decisiones, reviews, lecciones,
  cobertura, plan history y policy siguen siendo materiales.
- `decision_deliberation_bindings` enlaza cada envelope con la deliberación original y distingue
  `original` de `semantic_reuse`.
- La reutilización ocurre dentro de la misma transacción y antes de reservar presupuesto.
- Toda reutilización emite `decision_deliberation_semantically_reused`; API, costo y Prometheus
  exponen llamadas evitadas.
- Repetir `enqueue` sobre un envelope ya enlazado resuelve el binding existente y no intenta
  insertarlo otra vez; retries del timer son apply-once.
- Un cambio material produce un hash distinto y vuelve a encolar normalmente.

## Verificación

La prueba focal crea dos envelopes con distinta provenance y confirma una deliberación, dos
bindings y una sola reserva. Otra prueba cambia el plantel y confirma un hash diferente.

- suite: `1059 passed, 1 skipped, 79 deselected`;
- `compileall`: pass;
- build engine con Docker legacy: pass (el plugin Buildx no está instalado localmente);
- smoke dentro de la imagen: migration SQLite 017 y helper semántico importables.

El rollout vivo se consigna aquí después del despliegue; controles de FPL permanecen
`shadow/A0`, `kill_switch=true` y `browser_writes=false`.

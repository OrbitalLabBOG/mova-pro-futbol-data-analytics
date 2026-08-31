---
type: implementation-evidence
name: "MOVA FPL — HV1-06C idempotencia semántica agentic"
created: 2026-08-30
updated: 2026-08-31
tags: [mova, fpl, agents, idempotency, cost, observability]
status: verified-production
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
- Status y métricas siguen el binding del envelope vigente, no una fila de reparación más nueva.
- Un cambio material produce un hash distinto y vuelve a encolar normalmente.

## Verificación

La prueba focal crea dos envelopes con distinta provenance y confirma una deliberación, dos
bindings y una sola reserva. Otra prueba cambia el plantel y confirma un hash diferente.

- suite: `1059 passed, 1 skipped, 79 deselected`;
- `compileall`: pass;
- build engine con Docker legacy: pass (el plugin Buildx no está instalado localmente);
- smoke dentro de la imagen: migration SQLite 017 y helper semántico importables.

## Rollout y evidencia viva

El contrato llegó a `main` y al VPS en el código de rollout `7a946ee`; checkout, imagen y
`runtime.git_sha` quedaron conciliados. SQLite aplicó migration 017 y PostgreSQL migration 020.
Los timers se pausaron durante la intervención y los ocho timers MOVA quedaron nuevamente
activos al terminar.

La prueba usó tres envelopes equivalentes del ciclo `2026-27-gw03`:

- original: `envelope_e4cb04a323d840ae41846963`;
- replay: `envelope_138bf025312b3a557ab8b081`;
- replay corregido: `envelope_fcfc492a8cf19f62a9be9e57`.

Los tres quedaron ligados a `deliberation_b0c81ab7c32480d938873d516be0e55d`. El worker ejecutó
una sola llamada real, asentó 19.804 tokens y produjo verdict `block`; los dos replays resolvieron
`semantic_reuse` sin reserva nueva. El segundo intento creado durante el descubrimiento del bug
de retry (`deliberation_676d69bc6e61a4ad65ef4d94db21e7db`) se reparó antes de ejecución,
liberó su reserva y quedó auditable como `SEMANTIC_DUPLICATE_REPAIRED`; no consumió una llamada.

Evidencia operativa final:

- costo GW3: 2 usos evitados, 0 reservas activas y 0 reservas huérfanas;
- API `/api/v1/deliberation-bindings`: 1 binding original + 2 `semantic_reuse`;
- Prometheus: `mova_agent_deliberation_semantic_reuses=2` para GW y mes;
- import PostgreSQL `pgimport_e1a70e90979a471ab842512569820671`: 54 checks, 53 exactos,
  1 agregado y 0 fallos;
- backup post-rollout `job_c126af0c20bf4bf49653ae294b51e9cc` en
  `/opt/orbital/backups/mova-fpl/20260831T005447Z`, con integridad y hashes para las tres bases;
- `doctor`: 22 PASS, 0 WARN, 0 FAIL;
- readiness: 9 PASS, 6 PENDING, 0 BLOCKED.

No hubo operación browser ni escritura FPL. Los controles permanecen `shadow/A0`,
`kill_switch=true`, `browser_writes=false` y `compliance=pending`; esta mejora reduce costo y
ruido, pero no constituye una promoción de autonomía.

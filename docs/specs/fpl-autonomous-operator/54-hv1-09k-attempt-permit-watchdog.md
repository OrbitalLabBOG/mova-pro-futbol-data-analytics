---
type: deployment-evidence
name: "HV1-09K — Attempt permit watchdog"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, agents, watchdog, permits, recovery, observability]
status: verified-live
---

# HV1-09K — Attempt permit watchdog

## Problema cerrado

HV1-10D hacía fail-closed el consumo de un permiso, pero el plano de control no distinguía un
permiso sano de uno alterado o perdido hasta que el worker intentaba usarlo. Tampoco cerraba por sí
solo una autorización no consumida después de su TTL ni alertaba un `started` cuyo proceso murió
antes del receipt terminal.

## Contrato implementado

Antes de evaluar la cola, el watchdog cambia `preparing|authorized→expired` cuando terminó el TTL.
La transición es condicional e idempotente y genera exactamente un
`agent_attempt_authorization_expired`; no elimina archivos, no crea una nueva autorización y no
ejecuta Codex.

La inspección independiente ahora cruza el ledger completo con `artifacts/research/permits/`:

- permiso activo dentro del directorio allowlisted y con nombre sujeto+autorización;
- archivo regular, no symlink y máximo 64 KiB;
- SHA-256 igual al sellado durable;
- schema, authorization, subject, request hash, ordinal y expiración coincidentes;
- `preparing` con gracia máxima de 60 segundos;
- `started` con `attempt_id`, `started_at` y terminal esperado antes de 15 minutos;
- archivo sin ninguna fila durable tolerado sólo durante la gracia anti-race de 60 segundos.

Cualquier violación degrada el watchdog y reutiliza el P1 deduplicado
`Agent queue integrity unhealthy`. Al desaparecer la causa, el mecanismo causal existente resuelve
el incidente. `/api/v1/agent-queue`, `doctor` y Prometheus reciben el mismo estado sanitizado;
`mova_agent_queue_permits` informa sólo el número de archivos visibles.

## Verificación y rollout

- expiración después de 601 segundos y replay sin segunda transición/audit;
- permiso alterado abre P1 y degrada un scheduler sano;
- `started` durante 901 segundos sin terminal se reporta como estancado;
- permiso huérfano después de la gracia se reporta;
- regresión focal: 20 passed;
- suite completa: 1.195 passed, 1 skipped, 79 deselected;
- sin migración nueva: usa SQLite 21 y PostgreSQL 24 existentes;
- `git diff --check` y bytecode Python válidos.

Producción:

- commit funcional, checkout e imagen engine/API: `a213ea7`;
- watchdog vivo: `ok`, cero requests, cero permisos, cero anomalías y cero expiraciones;
- `/api/v1/agent-queue` sano y gauge `mova_agent_queue_permits 0` visible;
- doctor 23/23, safety `safe_to_wait` y ocho timers activos;
- PostgreSQL shadow 24, sync idempotente `pgimport_5c5c9871570449f696978859824ee101`
  y paridad 57/57;
- backup pre SQLite `/opt/orbital/backups/mova-fpl/20260831T060155Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T060156Z`;
- backup post forzado SQLite `/opt/orbital/backups/mova-fpl/20260831T060410Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T060410Z`.

No se fabricó una request agentic en producción para provocar una anomalía. Los cuatro fallos se
demostraron de forma hermética y el runtime vivo verificó el camino sano y la nueva telemetría.

## Autoridad

La reconciliación sólo cierra capacidad expirada y observa integridad. No puede reservar budget,
crear requests, llamar modelos ni operar FPL. Shadow/A0, kill switch y browser writes permanecen
sin cambios.

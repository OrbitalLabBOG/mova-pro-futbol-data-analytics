---
type: deployment-evidence
name: "HV1-09J — Agent attempt ledger and bounded replay"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, agents, retries, cost, observability, audit]
status: verified-live
---

# HV1-09J — Agent attempt ledger and bounded replay

## Problema cerrado

El worker guardaba `events.jsonl` y `error.json` por ID lógico de research/deliberation. Un retry
sobrescribía la evidencia anterior y, si el proceso terminaba antes de producir un resultado
importable, el timer podía volver a pagar la misma inferencia indefinidamente. El presupuesto
reservaba el subject lógico, pero no existía una identidad durable por ejecución física.

## Contrato implementado

- antes de invocar Codex se escribe un receipt append-only `started` con `attempt_id` único;
- después se escribe `finished` como `succeeded|failed`, duración, presencia de salida y tokens
  cuando el CLI los expone;
- logs de eventos, error y normalización usan `run_id + attempt_id` y nunca se sobrescriben;
- los receipts no contienen prompt, URL de auth, stderr ni credenciales;
- nombre, schema, identidad, SHA de request, tipos, tiempo, tamaño y path se validan fail-closed;
- replay exacto del receipt es idempotente; mismo evento con otro SHA va a cuarentena;
- `research-cycle.sh` importa receipts antes de resultados y también después de un exit no cero;
- dos `started` sin ningún éxito agotan la request, incluso si faltan `finished` por un hard kill;
- al agotarse, la corrida queda `rejected`, la reserva se carga conservadoramente y sólo la request
  regular bajo el inbox allowlisted se mueve a cuarentena;
- un receipt exitoso evita el cierre aunque exista un fallo previo.

Persistencia y consulta:

- SQLite migration 019: `agent_worker_attempt_events`;
- PostgreSQL shadow migration 022: `agent.worker_attempt_events`;
- `mova strategy attempts import|status`;
- `GET /api/v1/agent-attempts` y `GET /api/v1/agent-attempt-events`;
- `mova_agent_worker_attempts{status=...}` y `mova_agent_worker_exhausted_subjects`.

## Verificación

- suite completa: 1.182 passed, 1 skipped, 79 deselected;
- sintaxis Node/Bash, compileall, Compose y `git diff --check`: pass;
- fixtures: replay idéntico, replay alterado, dos fallos, hard-stop por dos starts y éxito posterior;
- producción, checkout, env, engine y research alineados a `3248572`;
- migraciones vivas SQLite 19 y PostgreSQL 22 aplicadas sin drift;
- primer import: `pgimport_e5d8fffe5af24dc8929bc2fee504df0e`, paridad 56/56;
- API y métricas vivas: cero intentos históricos, cero fallos, cero subjects agotados;
- doctor 23/23, watchdog `ok`, safety `safe_to_wait` y cero P0/P1 abiertos;
- readiness 15/23 pass, 8 pending, 0 blocked;
- backup previo SQLite `/opt/orbital/backups/mova-fpl/20260831T050957Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T050958Z`;
- backup PostgreSQL posterior `/opt/orbital/backups/mova-fpl/postgres/20260831T051226Z`.

No se ejecutó una inferencia real para fabricar evidencia: eso habría consumido presupuesto sin una
necesidad deportiva. Las pruebas de fallo son herméticas. El ledger empieza hacia adelante; no puede
reconstruir tokens de los 17 replays históricos cuyos logs ya habían sido sobrescritos.

## Autoridad

El cambio reduce costo y mejora auditoría, pero no amplía permisos. Producción conserva
`shadow/A0`, kill switch activo, compliance pendiente y browser writes deshabilitado. Supabase no
recibe datos operativos; sólo el snapshot PM de este avance.

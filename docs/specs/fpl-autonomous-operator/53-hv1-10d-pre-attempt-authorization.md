---
type: deployment-evidence
name: "HV1-10D — Pre-attempt authorization"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, agents, authorization, budget, deadline, idempotency]
status: verified-live
---

# HV1-10D — Pre-attempt authorization

## Problema cerrado

HV1-10C contabilizaba correctamente un retry después de ejecutarlo, pero el worker decidía el
siguiente start mirando sólo receipts en disco. Podía iniciar una segunda llamada que luego
resultara fuera del budget por job/GW/mes o demasiado cerca del deadline. El límite de dos evitaba
un loop infinito, pero el gasto seguía autorizado demasiado tarde.

## Contrato implementado

Por cada llamada física, el host:

1. selecciona un research/deliberation durable en `queued`;
2. verifica archivo allowlisted y `request_sha256` byte-lógico;
3. recalcula starts, éxitos, consumo previo exacto/conservador y ordinal;
4. proyecta tokens y usos contra límites job, GW y mes;
5. exige más de 70 minutos hasta deadline;
6. crea una autorización durable y un permiso inmutable con TTL máximo de diez minutos;
7. sella el SHA del permiso antes de levantar el worker.

El worker sólo selecciona requests con un permiso vigente cuyo subject, tipo, hash y ordinal
coinciden. Receipts v2 incluyen `authorization_id`; el host verifica el SHA del permiso y aplica
`authorized→started→finished`. El mismo permiso se reutiliza idempotentemente antes del start; un
segundo start requiere una nueva autorización. Un bloqueo repetido por misma causa y ordinal no
duplica el audit event.

Persistencia y observabilidad:

- SQLite migration 021: `agent_attempt_authorizations` y vínculo en receipts;
- PostgreSQL migration 024: `agent.attempt_authorizations`;
- `mova strategy attempts authorize|import|status`;
- API de attempts existente incluye conteos por estado de autorización;
- Prometheus: `mova_agent_attempt_authorizations{status=...}`;
- permisos inmutables en `artifacts/research/permits/`, sin prompt, auth ni stderr.

## Verificación

- suite: 1.191 passed, 1 skipped, 79 deselected;
- pruebas focales: permiso/replay idempotente, receipt v2, retry permitido bajo budget, retry
  bloqueado 130/120 antes de Codex, cutoff final, SHA alterado y bloqueo sin inflación de audit;
- ejecución real del worker sin permiso: exit 75, cero receipts y cero llamada Codex;
- commit funcional `5eccabc`, corrección de mapping PostgreSQL `2fd8973`;
- migraciones vivas SQLite 21 y PostgreSQL 24;
- import exitoso `pgimport_5301734b294b4b84ad489cce1875a957`, paridad 57/57;
- producción alineada a `2fd8973`; doctor 23/23, watchdog `ok`, safety `safe_to_wait`;
- `mova strategy attempts authorize` vivo sin cola: `skipped`, exit 75, cero autorizaciones;
- todos los timers activos y totales financieros históricos intactos.

Durante el rollout, el primer import PostgreSQL falló por un rename incorrecto de
`budget_snapshot_json`; se corrigió sin reescribir la migración aplicada, se añadió un test del
mapping y la nueva importación completó 57/57. No hubo inferencias ni cambios FPL.

Backups:

- pre SQLite: `/opt/orbital/backups/mova-fpl/20260831T054718Z`;
- pre PostgreSQL: `/opt/orbital/backups/mova-fpl/postgres/20260831T054719Z`;
- post SQLite: `/opt/orbital/backups/mova-fpl/20260831T055115Z`;
- post PostgreSQL: `/opt/orbital/backups/mova-fpl/postgres/20260831T055115Z`.

## Autoridad

El permiso autoriza exclusivamente una inferencia read-only, nunca una operación FPL. Producción
sigue `shadow/A0`, kill switch activo, compliance pendiente y browser writes deshabilitado.
Supabase conserva sólo el snapshot PM.

---
type: deployment-evidence
name: "HV1-06D — Orphan deliberation recovery"
created: 2026-08-31
updated: 2026-08-31
tags: [mova, fpl, agents, idempotency, cost, recovery, audit]
status: verified-live
---

# HV1-06D — Orphan deliberation recovery

## Incidente observado

El timer agentic encontró repetidamente
`deliberation_b75f5d15aef360b5cc952630ef3fe21b.request.json`. El resultado era válido como
artefacto, pero no existía una fila `decision_deliberations` con ese ID porque el envelope ya
estaba ligado por reutilización semántica a una deliberación anterior. El importador rechazaba el
resultado con `deliberación no registrada`, movía solo el resultado y dejaba el request en
`inbox/`; el worker lo retomaba en la siguiente cadencia.

Journald conserva 17 rechazos con la misma identidad desde las 00:00 UTC hasta las 04:23 UTC del
31 de agosto. Eso demuestra repetición real de inferencia, no una alerta falsa. Los eventos JSONL
anteriores se sobrescribieron por identidad, por lo que no se inventa un total histórico de
tokens; el uso exacto del incidente no es recuperable.

El timer se detuvo de forma reversible a las 04:27 UTC mientras se reparó el ciclo. Collectors,
API, PostgreSQL, watchdog y demás timers permanecieron operativos.

## Contrato corregido

- antes del worker, `strategy deliberate import` barre requests huérfanos con más de 60 segundos;
- la gracia evita competir con un enqueue concurrente;
- requests con lifecycle terminal también se retiran cuando no existe resultado pendiente;
- un resultado rechazado cuarentena conjuntamente el request correspondiente;
- evidencia preexistente nunca se sobrescribe: una colisión recibe hash y secuencia;
- cada cuarentena nueva registra `audit_events` con motivo, hashes e identidad, sin prompt;
- el resultado incluye conteo y detalle sanitizado de requests retirados;
- el worker rechaza independientemente cualquier ID cuyo resultado ya tenga tombstone en
  `quarantine/`;
- replay del importador es no-op y no reserva presupuesto ni invoca Codex.

## Pruebas

- request no registrado y viejo: cuarentena antes del worker;
- request no registrado reciente: preservado durante la ventana anti-race;
- resultado huérfano: request y resultado retirados conjuntamente;
- colisión de evidencia: el artefacto anterior permanece byte a byte;
- contrato estático del worker: tombstone de cuarentena obligatorio;
- `node --check`: pass;
- suite completa: 1.170 passed, 1 skipped, 79 deselected;
- `git diff --check`: pass.

## Evidencia viva

- fix primario `f8fdecd`, auditoría `268860a` y defensa del worker `67372cd`;
- checkout, `MOVA_GIT_SHA`, `MOVA_IMAGE_TAG`, engine y research alineados en `67372cd`;
- primera pasada viva: `terminal_requests_quarantined=1`, motivo
  `unregistered_request`, sin resultados procesados;
- segunda pasada inmediata: `terminal_requests_quarantined=0`, cero mutaciones;
- `inbox/` y `outbox/` vacíos; request y resultado originales preservados en `quarantine/`;
- ciclo systemd posterior: exit 75 esperado, `outside_research_window`, cero request y conteo de
  rechazos 17→17; el modelo no volvió a ejecutarse;
- timer agentic reactivado en estado `active`;
- API ready; doctor 22/22; watchdog `ok`; readiness 15/23, sin blockers;
- PostgreSQL `pgimport_b00efc09c4294b6fb0f8f9f65a2f6daa`: 55/55 y paridad pass;
- backup previo SQLite `/opt/orbital/backups/mova-fpl/20260831T043114Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T043123Z`;
- backup posterior SQLite `/opt/orbital/backups/mova-fpl/20260831T043534Z` y PostgreSQL
  `/opt/orbital/backups/mova-fpl/postgres/20260831T043535Z`.

## Autoridad y límite

La reparación no toca el equipo FPL ni altera la decisión deportiva. Producción conserva
`shadow/A0`, kill switch activo, compliance pendiente y browser writes deshabilitado. Los 17
reintentos históricos no quedaron asentados individualmente en `cost_ledger` porque nunca fueron
importables; el contrato nuevo impide que el patrón continúe y audita toda cuarentena futura.

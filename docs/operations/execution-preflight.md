---
type: runbook
name: "MOVA FPL — policy de autonomía y preflight"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, execution, preflight, autonomy, guardrails]
status: active
---

# Policy de autonomía y preflight

HV1-07A/B introduce la frontera durable previa al browser. HV1-07C añade la reserva apply-once,
lease, límite de ambigüedad y verificador post-reload. El driver de clicks permanece desconectado
en producción: los controles A0 y el contenedor browser conservan las escrituras apagadas.

## Contrato

```text
DecisionEnvelope inmutable
  + manifest y team state releídos
  + controles append-only
  + deadline/incidentes/ejecución previa
  → AutonomyPolicy determinista
  → ExecutionPlan blocked | authorized | noop
```

El artifact cumple
[`execution-plan-v1.schema.json`](../specs/fpl-autonomous-operator/contracts/execution-plan-v1.schema.json).
Conserva hashes de envelope/manifest, fingerprints pre/post, diff exacto, deadline, controles,
gates y clave idempotente. `authorized` significa maduro para un executor futuro; por sí mismo no
produce escrituras.

## Operar

```bash
mova execute status
mova execute preflight \
  --actor codex \
  --reason "rehearsal shadow antes del deadline GW3" \
  --idempotency-key "execution-preflight:2026-27:gw03:rehearsal-01"

curl -s http://127.0.0.1:8787/api/v1/execution-plans?limit=5 | jq
curl -s http://127.0.0.1:8787/api/v1/execution-preflight-checks?limit=50 | jq
curl -s http://127.0.0.1:8787/metrics | grep '^mova_execution_'
```

`preflight` persiste evidencia y exige actor, razón y clave. Repetir la clave devuelve el mismo
plan. Una nueva observación usa una clave nueva y supersede el plan anterior, sin editar historia.
El import PostgreSQL shadow copia planes y checks como evidencia consultable; SQLite continúa
siendo el writer hasta el cutover general de HV1-02.

Desde HV1-07C cada tick que produce un `DecisionEnvelope` ejecuta también el preflight con una
clave derivada del envelope. Esto crea evidencia `blocked`, `noop` o `authorized`; nunca reclama
un lease ni inicia el navegador por sí solo.

## Lifecycle apply-once

```text
authorized plan
  → prepared
  → claimed (token opaco, lease 30..600 s)
  → applying  ← desde aquí todo fallo es write-ambiguous
  → verified | ambiguous
```

Los estados `failed`, `blocked` y `expired` sólo son terminales antes de `applying`. Un token se
guarda únicamente como SHA-256 y se entrega una vez; `begin`, `finalize` y `fail` lo leen por
`stdin`, nunca como argumento. Un segundo claim falla. Otro idempotency key no puede reservar el
mismo plan.

```bash
mova execute prepare \
  --plan-id execplan_... \
  --adapter browser \
  --actor mova-executor \
  --reason "R2 promovido y gates revalidados" \
  --idempotency-key "execution:2026-27:gw03:r2:01"

mova execute claim \
  --execution-id execution_... \
  --actor mova-executor \
  --reason "inicio del adapter"

printf '%s' "$CLAIM_TOKEN" | mova execute begin \
  --execution-id execution_... --pre-state /run/mova/pre-state.json \
  --actor mova-executor --reason "GET privado pre-write idéntico" \
  --claim-token-stdin

printf '%s' "$CLAIM_TOKEN" | mova execute finalize \
  --execution-id execution_... --post-state /run/mova/post-state.json \
  --actor mova-executor --reason "GET privado posterior al reload" \
  --claim-token-stdin
```

No guardar `CLAIM_TOKEN` en shell history, logs, artifacts ni PostgreSQL. El wrapper productivo
deberá mantenerlo en memoria/pipe y borrar los JSON temporales sanitizados al terminar.

`prepare` vuelve a validar deadline, estado privado, incidentes y controles. Además sella un
`browser-command-bundle-v1` con exactamente siete operaciones R2: pre-read, XI/banca, C, VC,
commit único, reload y post-read. El adapter R3 no existe todavía: transfers, hits y chips fallan
cerrados aunque un plan futuro llegara autorizado.

## Riesgo y autoridad

| Riesgo | Acciones | Nivel mínimo |
| --- | --- | --- |
| R0 | diff vacío; lectura/no-op | A0 |
| R2 | XI, banca, capitán o vice | A2 |
| R3 | transfer, hit o chip | A3 |

Una acción solo queda `authorized` con: envelope staged, manifest ligado, team state válido,
fresco y sin cambio, fase entre preflight y execution window, deadline abierto, cero P0/P1, kill
switch apagado, browser writes habilitado, compliance aprobado, nivel suficiente, modo
`autonomous` y ausencia de ejecución previa. En `guarded` explicita aprobación humana pendiente y
permanece bloqueada.

`noop` nunca se envía al browser. `verified` exige que el GET privado posterior al reload
reconstruya exactamente el fingerprint de la decisión. Un mismatch queda `ambiguous`, abre un P0
y prohíbe retry automático. Transfers, hits y chips no tendrán un rollback automático ficticio.

## Recuperación

- `TEAM_STATE_FRESH` o `TEAM_STATE_FINGERPRINT_MATCH`: refrescar estado privado, regenerar
  manifest/envelope y usar una clave nueva.
- `EXECUTION_WINDOW`: esperar la fase; no alterar reloj ni phase persistido.
- `NO_OPEN_P0_P1`: resolver el incidente con evidencia antes de reintentar.
- gates de controles: cambiar controles solo mediante `mova control`, con actor y razón.
- hash inválido: bloquear, restaurar artifact/DB desde backup y verificar antes de decidir.

Rollout inicial: `shadow / A0`, `kill_switch=true`, `browser_writes=false`. Por tanto, un plan con
acciones debe quedar bloqueado; ese es el rehearsal seguro esperado.

## Observabilidad

- API: `/api/v1/execution-attempts` y `/api/v1/execution-attempt-events`;
- Prometheus: `mova_execution_attempt_status` y `mova_execution_attempts_total`;
- SQLite migration 010: intento + ledger de transiciones append-only;
- PostgreSQL shadow migration 012: espejo consultable, nunca writer;
- artifacts: `execution-commands/<cycle>/` y `execution-evidence/<cycle>/`.

El snapshot accessibility vivo se valida por nombres accesibles y no por refs `@eN`, que son
efímeros. El contrato requiere sesión autenticada, deadline, cuatro chips y 15 controles
`Switch player`. Que el DOM pase este check sólo habilita el adapter a seguir validando; no
concede autoridad.

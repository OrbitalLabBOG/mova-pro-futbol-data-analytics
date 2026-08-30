---
type: runbook
name: "MOVA FPL — policy de autonomía y preflight"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, execution, preflight, autonomy, guardrails]
status: active
---

# Policy de autonomía y preflight

HV1-07A/B introduce la frontera durable previa al browser. El sistema puede sellar el diff exacto,
clasificar su riesgo y demostrar por qué una acción está autorizada o bloqueada. Este corte **no**
incluye `apply`: no contiene clicks, endpoints de escritura ni una ruta alternativa hacia FPL.

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

`noop` nunca se envía al browser. El executor de HV1-07C deberá releer FPL, comparar el
fingerprint post-acción y abrir incidente ante cualquier diferencia. Transfers, hits y chips no
tendrán un rollback automático ficticio.

## Recuperación

- `TEAM_STATE_FRESH` o `TEAM_STATE_FINGERPRINT_MATCH`: refrescar estado privado, regenerar
  manifest/envelope y usar una clave nueva.
- `EXECUTION_WINDOW`: esperar la fase; no alterar reloj ni phase persistido.
- `NO_OPEN_P0_P1`: resolver el incidente con evidencia antes de reintentar.
- gates de controles: cambiar controles solo mediante `mova control`, con actor y razón.
- hash inválido: bloquear, restaurar artifact/DB desde backup y verificar antes de decidir.

Rollout inicial: `shadow / A0`, `kill_switch=true`, `browser_writes=false`. Por tanto, un plan con
acciones debe quedar bloqueado; ese es el rehearsal seguro esperado.

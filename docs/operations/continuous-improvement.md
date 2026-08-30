---
type: runbook
name: "MOVA FPL — mejora continua controlada"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, learning, review, costs, promotion]
status: active-shadow
---

# Mejora continua controlada

## Contrato

El settlement produce `change_proposals`. El gate permite únicamente:

```text
proposed → testing → accepted
         ↘ rejected ↗
```

`accepted` significa que la hipótesis se convirtió en memoria validada; no significa que un
modelo, prompt, política o control haya sido desplegado. La aplicación real conserva su propio
workflow de código, tests, shadow, aprobación y rollback.

Las tablas `change_proposal_evaluations` y `lessons` son append-only salvo el estado visible de
la propuesta. Cada transición conserva actor, razón, clave idempotente, hash y evidencia. El
reintento con la misma clave y contenido se reutiliza; una colisión de contenido falla cerrada.

## Operación

```bash
mova improve status --season 2026-27 --gw 1

mova improve transition --proposal-id proposal_... --to testing \
  --evidence /path/testing.json --actor codex \
  --reason "abre backtest causal" --idempotency-key "improve:proposal:testing:v1"

mova improve transition --proposal-id proposal_... --to accepted \
  --evidence /path/accepted.json --actor codex \
  --reason "cumple criterio versionado" --idempotency-key "improve:proposal:accepted:v1"
```

La evidencia `testing` exige `experiment_id` y `test_plan`. `accepted` exige además
`evaluated_at`, `acceptance_passed=true`, métricas `baseline` y `candidate`, al menos una
referencia en `test_evidence` y `rollback_plan`. `rejected` exige `rejection_reason`.

La API loopback expone `/api/v1/improvement`, `/api/v1/change-proposal-evaluations` y
`/api/v1/lessons`. El bloque `costs` informa tokens, usos por suscripción, costo conocido y
cuántos usos carecen de costo atribuible. Un `estimated_cost_usd=0` nunca se inventa para Codex
por suscripción; esos usos permanecen explícitamente desconocidos.

El presupuesto agentic se consulta de forma independiente:

```bash
mova cost report --season 2026-27 --gw 3 --month 2026-08
curl --fail --silent http://127.0.0.1:8787/api/v1/costs
```

La política inicial reserva 120.000 tokens por llamada y limita cada job a 160.000, cada GW a
900.000/20 usos y cada mes a 3.000.000/60 usos. Son límites operativos configurables, no una
estimación monetaria. La reserva se escribe atómicamente con el job: si una dimensión excede el
techo, el request no queda en inbox ni entra en la cola. Al importar, se reconcilia con uso real;
si el resultado se rechaza, la reserva se conserva como `charged` hasta una recuperación válida.

La API `/api/v1/budget-reservations` expone las últimas reservas y Prometheus publica
`mova_agent_budget_tokens`, `mova_agent_budget_uses` y
`mova_agent_budget_within_limit`, por scope `gameweek|month`.

## Recuperación y límites

- Una transición inválida no modifica la propuesta.
- Una aceptación no ejecuta código ni cambia controles.
- Para corregir una hipótesis, rechazarla y crear una propuesta nueva desde evidencia posterior;
  no sobrescribir evaluaciones.
- El reviewer causal automático sigue pendiente de HV1-08; no simularlo antes de
  `finished + data_checked`.
- PostgreSQL recibe estas tablas por el import shadow; SQLite continúa como writer oficial.

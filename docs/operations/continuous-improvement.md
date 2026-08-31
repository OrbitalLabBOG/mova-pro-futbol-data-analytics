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

`accepted` significa que la hipótesis se convirtió en memoria validada; por sí sola no despliega
un modelo, prompt, política o control. Para modelos existe un segundo lifecycle explícito:

```text
accepted lesson → prepared → shadow → promoted
                              ↘ rolled_back ←┘
```

El release solo admite el bundle completo `minutes+points`. No ejecuta scripts, patches ni código
arbitrario y no puede cambiar controles de autonomía o browser.

El reviewer causal corre automáticamente después de `analytics reconcile` únicamente cuando
existen settlement oficial `finished + data_checked` y scorecard baseline final. También puede
accionarse de forma auditada:

```bash
mova review auto --gw 2 --actor codex \
  --reason "scorecard final disponible" --idempotency-key "causal:2026-27:gw2:v1"
```

Clasifica `data/freshness`, `model/calibration`, `optimizer`, `research/context`, `strategy`,
`execution` y `variance`. Una observación aislada nunca crea propuesta: una causa accionable debe
aparecer al menos tres veces antes de abrir experimento. `not_ready` no muta jobs ni memoria.

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

mova improve release prepare --proposal-id proposal_... --manifest /path/release.json \
  --actor codex --reason "sella candidato" --idempotency-key "release:proposal:prepare:v1"
mova improve release shadow --release-id release_... --actor codex \
  --reason "inicia inferencia paralela" --idempotency-key "release:proposal:shadow:v1"
mova improve release status
mova improve release promote --release-id release_... --actor codex \
  --reason "gate multi-GW aprobado" --idempotency-key "release:proposal:promote:v1"
mova improve release rollback --release-id release_... --actor codex \
  --reason "degradación observada" --idempotency-key "release:proposal:rollback:v1"
```

Manifest mínimo:

```json
{
  "schema": "mova-model-bundle-candidate-v1",
  "models": {
    "minutes": {"version": "1.2.0", "artifact_sha256": "<64 hex>"},
    "points": {"version": "1.2.0", "artifact_sha256": "<64 hex>"}
  },
  "promotion_policy": {"min_final_gameweeks": 3}
}
```

Las rutas se derivan de `MOVA_ARTIFACT_ROOT/models`; el manifest no puede inyectar una ruta. En
`prepare`, el servicio vuelve a calcular ambos hashes y captura el bundle activo como rollback.
En `shadow`, `mova analytics project` agrega la variante
`model_release_shadow:<release_id>` sin sustituir el baseline. `promote` exige al menos tres GWs
finales pareadas, cero alertas de drift por defecto, MAE de puntos no mayor a 1,05× el baseline y
delta de ECE p60 no mayor a 0,02. Los límites solo pueden ajustarse dentro de rangos acotados.

La promoción escribe `active_model_bundle` en el ledger append-only. Analytics y el tick de
decisión resuelven ese puntero y verifican los hashes antes de cargar modelos. El rollback restaura
el bundle anterior y, cuando corresponde, la identidad del release que había sido superseded.
Los endpoints read-only son `/api/v1/model-bundle-releases` y
`/api/v1/model-bundle-release-events`.

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
mova cost overrun --reservation-id <reservation_id> --to reviewed \
  --action optimize_prompt --actor <actor> --reason <reason> \
  --idempotency-key <key>
curl --fail --silent http://127.0.0.1:8787/api/v1/costs
curl --fail --silent http://127.0.0.1:8787/api/v1/budget-overrun-events
```

La política inicial reserva 120.000 tokens por llamada y limita cada job a 160.000, cada GW a
900.000/20 usos y cada mes a 3.000.000/60 usos. Son límites operativos configurables, no una
estimación monetaria. La reserva se escribe atómicamente con el job: si una dimensión excede el
techo, el request no queda en inbox ni entra en la cola. Al importar, se reconcilia con uso real;
si el resultado se rechaza, queda un cargo estimado terminal `charged` porque el proveedor ya
pudo consumir la llamada aunque no exista usage confiable. Un replay usa un subject nuevo y no
libera ese cargo histórico.

`mova cost report` separa `consumed`, `reserved` y `charged_estimate`. `committed` suma los tres:
una presentación más clara nunca recupera presupuesto. Si el uso real supera el límite por job,
el resultado conserva su validación deportiva pero el settlement emite warning, el reporte queda
`job_overrun_observed` y Prometheus publica conteo y exceso. El runtime no puede desconsumir una
llamada ya terminada. Una reserva `reserved` cuyo subject ya no está queued se expone como
`orphaned_reservation_observed`; sigue comprometida y exige diagnóstico, no borrado manual.

Cada overrun individual recorre un ledger inmutable `open -> reviewed -> resolved|waived`.
`reviewed` exige acción y razón; `resolved` exige una reserva posterior del mismo tipo de trabajo
y proveedor, liquidada dentro del límite, enlazada con `--followup-reservation-id`. `waived` es
una excepción humana explícita y nunca se automatiza. Replay con la misma clave y semántica
reutiliza evidencia; una clave reutilizada con otra transición falla sin mutar. El scorecard
mantiene economics en pending mientras exista un caso `reviewed_pending`.

La API `/api/v1/budget-reservations` expone las últimas reservas y Prometheus publica
`mova_agent_budget_tokens`, `mova_agent_budget_uses` y
`mova_agent_budget_within_limit`, por scope `gameweek|month`. También publica
`mova_agent_budget_job_overruns`, `mova_agent_budget_job_overrun_tokens` y
`mova_agent_budget_orphaned_reservations`. El lifecycle publica además
`mova_agent_budget_overrun_reviews{scope,status}` con labels acotados.

## Recuperación y límites

- Una transición inválida no modifica la propuesta.
- Una aceptación no ejecuta código ni cambia controles.
- Un release sin propuesta aceptada, artefactos intactos o shadow aprobado falla cerrado.
- Un candidato shadow que falla abre P2 y no invalida la proyección baseline.
- Rollback desde `shadow` solo retira el candidato; desde `promoted` restaura el puntero anterior.
- Para corregir una hipótesis, rechazarla y crear una propuesta nueva desde evidencia posterior;
  no sobrescribir evaluaciones.
- No simular ni forzar el reviewer antes de `finished + data_checked` y scorecard baseline.
- PostgreSQL recibe estas tablas por el import shadow; SQLite continúa como writer oficial.

---
type: runbook
name: "MOVA FPL — lifecycle de decisión shadow"
created: 2026-08-28
updated: 2026-08-31
tags: [mova, fpl, decision-envelope, validator, shadow]
status: active
---

# Lifecycle de decisión shadow

HV1-06A convierte la salida del engine en un paquete máquina reproducible. HV1-06B añade una
deliberación acotada de Strategist + Critic. El MILP sigue siendo la única autoridad que arma
plantillas; los roles comparan opciones y proponen una `Intervention` shadow, pero no reescriben
la decisión, no suavizan gates y no operan FPL.

## Flujo

```text
snapshot + team state + projection + plan + research
  → CycleManifest
  → live decision candidates JSON
  → deterministic validator
  → DecisionEnvelope blocked|staged
  → binding semántico → request sellada → Strategist → Critic → validación determinista
  → deliberation accepted|review_required|blocked + Intervention applied=false
  → ExecutionPlan + deterministic preflight (sin apply)
  → decision_runs + players + candidates + checks + audit
```

Cada corrida contiene exactamente:

- `do_nothing`: estado observado sin cambios;
- `milp_baseline`: MILP con el planner vigente, candidato seleccionado en shadow;
- `primary_alternative`: MILP sin chip o, si coincide con baseline, plantilla conservada con XI
  optimizado.

El acta Markdown es una vista para humanos. El tick consume el JSON producido por
`mova_fpl.cli.live --json-out`; nunca extrae valores con expresiones regulares.

La deliberación es hija del envelope y no lo modifica. El worker one-shot recibe únicamente el
envelope, su contexto sellado, el plan y señales ya incluidas en el manifest. Para este rol se
deshabilita web search: descubrir hechos nuevos pertenece exclusivamente al Researcher.

Antes de reservar presupuesto, el servicio calcula `semantic_input_sha256`. El hash incluye los
tres candidatos, validaciones, estado real del equipo, fase, research, memoria, plan y versiones
de modelo. Excluye IDs de envelope/manifest, timestamps de captura, rutas, batch IDs y SHA del
despliegue. Un envelope nuevo que solo difiere en esa provenance crea un binding
`semantic_reuse`, reutiliza el resultado anterior y no crea archivo de inbox, reserva ni llamada
LLM. Cualquier cambio material produce una deliberación nueva. Los envelopes siguen siendo
inmutables y cada reutilización queda auditada.

## Contrato Strategist + Critic

Strategist debe cubrir los tres candidatos exactamente una vez y solo puede proponer los campos
existentes de `Intervention`: multiplicadores acotados, chips a considerar/vetar, `lock_in`,
`lock_out` y `risk_lambda`. Los jugadores deben pertenecer al contexto sellado y la propuesta se
normaliza siempre con:

```json
{"policy_version":"bounded-deliberation-1.0.0","shadow_only":true,"applied":false}
```

Critic devuelve `accept`, `revise` o `block`. Todo hard blocker del envelope debe reaparecer con
el mismo código y severidad `block`; omitirlo o intentar aceptar ese envelope rechaza todo el
resultado y lo mueve a cuarentena. `accept` significa que el análisis fue aceptado como evidencia,
no que la propuesta tenga autorización operativa.

## Hard gates

El envelope queda `blocked` cuando falla cualquiera de estos checks:

| Código | Contrato |
| --- | --- |
| `CYCLE_MANIFEST_BOUND` | season/GW y hash corresponden al manifest sellado |
| `REQUIRED_COMPARATORS_PRESENT` | existen los tres escenarios obligatorios |
| `SELECTED_DECISION_LEGAL` | estructura y reglas del engine válidas |
| `TRANSFER_COST_ACCOUNTED` | hits, FTs, transferencias y exención de chip cuadran |
| `PRIOR_GAMEWEEK_SETTLED` | la GW previa está `finished + data_checked` |
| `TEAM_STATE_FRESH` | snapshot autenticado válido, fresco y usado por el solve |
| `ANALYTICS_APPROVED_CAUSAL` | batch aprobado para la GW objetivo |
| `RESEARCH_CONFLICTS_CLEAR` | cero conflictos materiales abiertos |
| `IRREVERSIBLE_ACTION_WINDOW` | transfer/hit/chip dentro de `refresh..execution_window` |
| `SEASON_PLAN_BOUND` | una acción irreversible está ligada al plan activo |
| `EXECUTION_AUTHORITY_SEPARATED` | el envelope no concede autoridad browser; policy posterior decide |

`hits` significa cantidad de transferencias pagadas. La liquidación y el xP descuentan
`hits × rules.hit_cost`; con la regla vigente, `1 hit = −4 puntos`.

## Consultar

```bash
mova status --json | jq '{decision,decision_envelope}'
mova strategy deliberate status
curl -s http://127.0.0.1:8787/api/v1/decision-envelopes?limit=5 | jq
curl -s http://127.0.0.1:8787/api/v1/decision-candidates?limit=20 | jq
curl -s http://127.0.0.1:8787/api/v1/decision-checks?limit=30 | jq
curl -s http://127.0.0.1:8787/api/v1/deliberations?limit=5 | jq
curl -s http://127.0.0.1:8787/api/v1/deliberation-bindings?limit=20 | jq
curl -s http://127.0.0.1:8787/api/v1/deliberation-risks?limit=30 | jq
curl -s http://127.0.0.1:8787/metrics | grep '^mova_decision_'
curl -s http://127.0.0.1:8787/metrics | grep '^mova_agent_deliberation_semantic_reuses'
```

El contrato está en
[`decision-envelope-v1.schema.json`](../specs/fpl-autonomous-operator/contracts/decision-envelope-v1.schema.json).
El output de los roles valida además contra
[`decision-deliberation.schema.json`](../../deploy/research/decision-deliberation.schema.json).
La frontera posterior está documentada en
[policy de autonomía y preflight](execution-preflight.md).

## Estados y recuperación

```text
blocked → nueva evidencia/manifest → nuevo envelope
staged  → revisión/autoridad posterior → approved/executed en HV1-07
blocked|staged anterior → superseded al sellar una revisión nueva
envelope vigente → deliberation queued → accepted|review_required|blocked
envelope semánticamente equivalente → binding semantic_reuse → resultado previo, cero presupuesto
output inválido → rejected + quarantine; nunca intervención parcial
request sin fila durable (>60 s) → quarantine antes del worker; cero inferencia
resultado ya en quarantine → tombstone terminal; el worker omite ese ID
```

Un `blocked` esperado no degrada el worker ni abre un incidente: demuestra que el gate detuvo una
propuesta inmadura. Un fallo al generar, validar o persistir el envelope sí falla el job y usa el
runbook general del operador. Los artefactos anteriores no se editan; el replay usa
`manifest.content_sha256`, versiones del engine y los tres candidatos sellados.

`mova strategy deliberate import` es también el reconciliador pre-worker. Retira requests
huérfanos o terminales, mueve conjuntamente el request de un resultado rechazado y emite
`decision_deliberation_request_quarantined` o
`decision_deliberation_artifacts_quarantined` en `audit_events`. Una segunda pasada debe reportar
cero procesados y cero cuarentenas. No borrar manualmente evidencia: las colisiones se conservan
con hash y secuencia.

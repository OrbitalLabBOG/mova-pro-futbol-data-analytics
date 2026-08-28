---
type: runbook
name: "MOVA FPL — lifecycle de decisión shadow"
created: 2026-08-28
updated: 2026-08-28
tags: [mova, fpl, decision-envelope, validator, shadow]
status: active
---

# Lifecycle de decisión shadow

HV1-06A convierte la salida del engine en un paquete máquina reproducible. El MILP sigue siendo
la única autoridad que arma plantillas; el harness compara opciones y aplica gates, pero no
reescribe la decisión ni opera FPL.

## Flujo

```text
snapshot + team state + projection + plan + research
  → CycleManifest
  → live decision candidates JSON
  → deterministic validator
  → DecisionEnvelope blocked|staged
  → decision_runs + players + candidates + checks + audit
```

Cada corrida contiene exactamente:

- `do_nothing`: estado observado sin cambios;
- `milp_baseline`: MILP con el planner vigente, candidato seleccionado en shadow;
- `primary_alternative`: MILP sin chip o, si coincide con baseline, plantilla conservada con XI
  optimizado.

El acta Markdown es una vista para humanos. El tick consume el JSON producido por
`mova_fpl.cli.live --json-out`; nunca extrae valores con expresiones regulares.

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
| `SHADOW_CONTROLS_ENFORCED` | `shadow/A0`, browser writes off y kill switch on |

`hits` significa cantidad de transferencias pagadas. La liquidación y el xP descuentan
`hits × rules.hit_cost`; con la regla vigente, `1 hit = −4 puntos`.

## Consultar

```bash
mova status --json | jq '{decision,decision_envelope}'
curl -s http://127.0.0.1:8787/api/v1/decision-envelopes?limit=5 | jq
curl -s http://127.0.0.1:8787/api/v1/decision-candidates?limit=20 | jq
curl -s http://127.0.0.1:8787/api/v1/decision-checks?limit=30 | jq
curl -s http://127.0.0.1:8787/metrics | grep '^mova_decision_'
```

El contrato está en
[`decision-envelope-v1.schema.json`](../specs/fpl-autonomous-operator/contracts/decision-envelope-v1.schema.json).

## Estados y recuperación

```text
blocked → nueva evidencia/manifest → nuevo envelope
staged  → revisión/autoridad posterior → approved/executed en HV1-07
blocked|staged anterior → superseded al sellar una revisión nueva
```

Un `blocked` esperado no degrada el worker ni abre un incidente: demuestra que el gate detuvo una
propuesta inmadura. Un fallo al generar, validar o persistir el envelope sí falla el job y usa el
runbook general del operador. Los artefactos anteriores no se editan; el replay usa
`manifest.content_sha256`, versiones del engine y los tres candidatos sellados.

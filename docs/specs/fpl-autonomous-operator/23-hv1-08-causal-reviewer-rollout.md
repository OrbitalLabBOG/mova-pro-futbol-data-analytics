---
type: deployment-evidence
name: "MOVA FPL — HV1-08 reviewer causal automático"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, hv1-08, reviewer, causality, learning, rollout]
status: verified-shadow
---

# HV1-08 — reviewer causal automático

## Resultado

El servicio analítico acciona un reviewer determinista después de `reconcile`. Solo crea review
si ya existen settlement oficial `finished + data_checked` y scorecard baseline final. Clasifica:

- `data/freshness`;
- `model/calibration`;
- `optimizer`;
- `research/context`;
- `strategy`;
- `execution`;
- `variance`.

Una causa accionable debe acumular dos ocurrencias históricas y reaparecer en una tercera GW para
crear `change_proposal`. La propuesta abre un experimento; no cambia modelo, prompt, policy ni
equipo. Un fallo del reviewer abre P2 propio y no invalida scorecards ya sellados.

## Verificación

| Check | Resultado |
| --- | --- |
| Git | `347860a` |
| VPS checkout/imagen | `1e80955` / `1e80955` |
| suite | 919 passed, 1 skipped esperado, 79 deselected |
| doctor | 22 PASS, 0 WARN, 0 FAIL |
| GW2 rollout check | `not_ready: settlement_not_closed` |
| causal jobs antes/después del check | 0 / 0 |
| execution attempts | 0 |
| controles | shadow, A0, compliance pending, kill switch true, browser writes false |
| backup SQLite | `20260830T175619Z` |
| backup PostgreSQL | `20260830T175620Z` |

El check live prueba el fail-closed: GW2 aún no estaba asentada y el comando no creó job,
artefacto, review ni propuesta. La primera ejecución causal real ocurrirá automáticamente en el
primer ciclo analítico posterior al settlement y scorecard final.

## Operación

```bash
mova review auto --gw 2 --actor codex \
  --reason "scorecard final disponible" --idempotency-key "causal:2026-27:gw2:v1"

curl --fail --silent http://127.0.0.1:8787/api/v1/gameweek-reviews
```

`not_ready` es una salida sana y no se fuerza. Un retry con la misma clave reutiliza el job y el
review. PostgreSQL sigue como shadow y Supabase continúa únicamente como seguimiento PM.

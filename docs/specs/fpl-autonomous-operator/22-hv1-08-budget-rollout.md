---
type: deployment-evidence
name: "MOVA FPL — HV1-08 budgets agentic fail-closed"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, hv1-08, budgets, costs, observability, rollout]
status: verified-shadow
---

# HV1-08 — budgets agentic fail-closed

## Alcance

Este corte añade control de consumo para los dos jobs con inferencia externa: investigación de
noticias y deliberación Strategist + Critic. No amplía autonomía, no ejecuta browser y no cambia
el equipo FPL. Supabase sigue fuera del runtime.

La política inicial es:

| Scope | Tokens | Usos |
| --- | ---: | ---: |
| reserva por llamada | 120.000 | 1 |
| job | 160.000 | 1 |
| gameweek | 900.000 | 20 |
| mes UTC | 3.000.000 | 60 |

La reserva se inserta en la misma transacción que el job. Un exceso deja auditoría
`agent_budget_blocked` y no crea job ni request en inbox. El import liquida tokens reales; un
resultado rechazado conserva la reserva como `charged` para no esconder consumo incierto.

## Contratos entregados

- SQLite migration `012_agent_cost_budgets`;
- PostgreSQL shadow migration `014_agent_cost_budgets`;
- tablas `cost_ledger` atribuido y `agent_budget_reservations`;
- `mova cost report --season/--gw/--month`;
- `/api/v1/costs` y `/api/v1/budget-reservations`;
- métricas `mova_agent_budget_tokens`, `mova_agent_budget_uses` y
  `mova_agent_budget_within_limit`;
- duración real del worker; búsquedas quedan `null` porque Codex CLI no expone el conteo;
- `mova backup --force` con actor, razón e idempotency key para capturas post-migración.

## Evidencia de verificación

| Check | Resultado |
| --- | --- |
| suite hermética | 912 passed, 1 skipped esperado, 79 integration/slow deselected |
| Compose / sintaxis worker | PASS |
| commit Git de feature | `ff2315b` |
| commit Git de backup auditado | `f61873f` |
| checkout/imagen VPS | `96eb2a9` / `96eb2a9` |
| SQLite | 3.53.4, migrations 1–12 |
| PostgreSQL | 17.11, migrations 1–14, shadow |
| import shadow | `pgimport_4c69c16a5571451ea015c0dd5f6bd73a` |
| tablas importadas | 48/48 PASS |
| doctor | 22 PASS, 0 WARN, 0 FAIL |
| timers | 7 activos |
| execution attempts | 0 |
| controles | shadow, A0, compliance pending, kill switch true, browser writes false |

El backfill vivo encontró 572.117 tokens/13 usos en agosto: 352.787 de research y 219.330 de
deliberación. GW3 lleva 219.330 tokens/11 usos; quedan 680.670 tokens y 9 usos. Todos los scopes
están `within_budget`. No se inventó costo USD para la suscripción ChatGPT.

## Backups y rollback

- pre-deploy SQLite: `/opt/orbital/backups/mova-fpl/20260830T172323Z`;
- pre-deploy PostgreSQL: `/opt/orbital/backups/mova-fpl/postgres/20260830T174247Z`;
- post-deploy SQLite: `/opt/orbital/backups/mova-fpl/20260830T174736Z`;
- post-deploy PostgreSQL: `/opt/orbital/backups/mova-fpl/postgres/20260830T174736Z`.

Rollback: mantener las migraciones aditivas, volver a imagen/checkout previo y conservar ledger,
reservas y auditoría. Los límites se cambian solo mediante configuración versionada y nuevo
rollout; no se fuerzan jobs bloqueados.

## Pendiente real

HV1-08 continúa parcial únicamente por el reviewer causal automático. GW2 aún tenía un fixture
sin iniciar y no estaba `finished + data_checked` durante este rollout; por eso no se fabricó un
review ni una atribución causal.

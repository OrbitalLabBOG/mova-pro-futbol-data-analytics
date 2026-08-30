---
type: evidence
name: "HV1-09 — autonomy readiness consolidado"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, autonomy, readiness, observability, rollout]
status: deployed-shadow
---

# HV1-09 — autonomy readiness consolidado

## Resultado

Se desplegó un gate read-only que responde qué nivel de autonomía está técnicamente sustentado y
qué evidencia falta. No cambia controles, no llama el browser y no promueve autoridad. Producción
permanece `shadow/A0`, `compliance=pending`, `kill_switch=true` y `browser_writes=false`.

Superficies entregadas:

- `mova readiness` y `mova readiness --require-level A1|A2|A3`;
- `GET /api/v1/readiness`;
- métricas `mova_autonomy_*` y `mova_postgres_distinct_gameweek_cycles`;
- 14 gates con estado `pass|pending|blocked`, evidencia y siguiente acción;
- conteo de ciclos PostgreSQL por GW auditada, inmune a reintentos repetidos;
- separación explícita entre `technical_eligible_level` y controles de activación.

## Evidencia de implementación

| Evidencia | Resultado |
| --- | --- |
| suite completa | `1005 passed, 1 skipped, 79 deselected` |
| pruebas focalizadas finales | `22 passed` |
| commit de feature | `dee7411` |
| revisión desplegada en `main` | `0ce1a7bc` |
| imagen API | `mova-fpl-engine:0ce1a7bc` |
| PostgreSQL verify | pass, 52 tablas, paridad pass |
| API/endpoint | schema `mova-autonomy-readiness-v1` |
| métricas | readiness up=1; nivel A0=1 |
| doctor live con red | 22 PASS, 0 WARN, 0 FAIL |
| timers | 8 timers MOVA activos |

Backups consistentes rodearon el cambio:

- predeploy: `/opt/orbital/backups/mova-fpl/20260830T214334Z`;
- postdeploy: `/opt/orbital/backups/mova-fpl/20260830T214549Z`.

## Primer reporte vivo

El reporte produjo `overall_status=not_ready`, `technical_eligible_level=A0` y:

| Estado | Cantidad |
| --- | ---: |
| pass | 8 |
| pending | 5 |
| blocked | 1 |

Evidencia pendiente:

1. GW2 todavía preliminar al corte por un fixture sin iniciar;
2. research v2 `0/3` GWs medidas;
3. capitanía R2 `0/3` rehearsals;
4. lineup R2 con entrypoint aún deshabilitado y `0/3` rehearsals;
5. PostgreSQL `1/3` ciclos de GW auditados.

Bloqueo estructural: R3 no tiene todavía contrato host para transferencias/chips. Ejecutar
`mova readiness --require-level A1` devolvió exit 2, como exige el comportamiento fail-closed.

## Decisión

HV1-09 queda completo como control transversal. No cierra HV1-02, HV1-05 ni HV1-07: hace sus
dependencias observables y consumibles por el agente sin fingir que el tiempo o los rehearsals ya
ocurrieron. Cualquier promoción futura exige que los gates pasen y, además, una aprobación
explícita separada que cambie los controles auditados.

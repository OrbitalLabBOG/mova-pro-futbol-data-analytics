---
work_key: WP-INIT-MOVA-FPL-ENGINE-003
title: "Walking skeleton - harness replay walk-forward ciego, baselines y traza"
work_type: workpack
spec_version: 1
spec_status: draft
priority: critical
estimated_hours: 14
parent_key: null
depends_on_keys: [WP-INIT-MOVA-FPL-ENGINE-001, WP-INIT-MOVA-FPL-ENGINE-002]
---

# WP-003 — Walking skeleton: harness, baselines y traza

## Objetivo y resultado

Cerrar el circuito completo de extremo a extremo **antes** de que existan los modelos
buenos: `replay("2025-26")` corre las 38 jornadas con una política deliberadamente tonta,
puntúa contra resultados reales, compara contra baselines y persiste cada paso en la traza.

El valor es de secuenciación: a partir de aquí, cada modelo que se enchufe se mide de
inmediato en vez de esperar al final. Es la mitigación principal de R-01.

## Requisitos cubiertos

REQ-F-007, REQ-F-008, REQ-F-009, REQ-F-010, REQ-Q-005

## No objetivos

- La política de decisión de este workpack **no pretende ser buena**. Es un stub
  (p. ej. maximizar xP ingenuo por precio) cuyo único fin es ejercitar el circuito.
- No se optimizan transferencias con MILP (eso es WP-006).

## Precondiciones y dependencias

- WP-001 (almacén y `as_of`) y WP-002 (reglas para puntuar) terminados.

## Superficie permitida

```
mova_fpl/engine/{__init__,runner,simulator,state,baselines}.py
mova_fpl/trace/{__init__,schema,writer,query}.py
mova_fpl/cli/backtest.py
tests/test_decide_identity.py
tests/test_replay_no_future_access.py
tests/test_trace_reproducibility.py
data/processed/trace.db   (nuevo)
```

## Interfaces y comportamiento

```python
decide(gw: int, state: State, config: Config) -> Decision       # LA función
replay(season: str, mode: Literal["named","anonymized"], seed: int) -> RunReport
```

En modo `anonymized`, nombres de jugador y equipo se sustituyen por identificadores
estables antes de llegar a la política. Para el motor determinista es indiferente; la
capacidad existe para medir contaminación cuando llegue el agente LLM.

Baselines obligatorios: template (más seleccionados), **techo con información perfecta**, y
selección aleatoria válida con semilla.

> **Señal de cambio (2026-08-07).** El promedio real del mánager no está en el histórico
> (H-24). Se sustituye por el techo, que mide qué fracción de lo alcanzable se capturó.

Cold start: `as_of(season, 1)` devuelve vacío. La política debe manejarlo explícitamente.

## Criterios de aceptación

| ID | Requisito | Criterio verificable |
| --- | --- | --- |
| AC-WP003-001 | REQ-F-008 | `replay("2025-26")` completa las 38 jornadas y reporta puntos por jornada y acumulados |
| AC-WP003-002 | REQ-F-008 | Durante toda la corrida, ninguna llamada de entrenamiento recibe filas con `GW >= T`; verificado por la instrumentación de WP-001 |
| AC-WP003-003 | REQ-F-008 | GW1 se resuelve en cold start sin excepción y sin acceder a datos de 2025/26 |
| AC-WP003-004 | REQ-F-009 | El reporte incluye los tres baselines (template, techo, aleatorio) y ninguno resulta cero por fallo de construcción |
| AC-WP003-005 | REQ-F-007 | Mismo `State` sintético produce `Decision` idéntico invocado desde el simulador y desde el runner en vivo |
| AC-WP003-006 | REQ-Q-005 | Dos corridas con la misma semilla y git sha producen traza idéntica salvo timestamps |
| AC-WP003-007 | REQ-F-010 | Consultando sólo la traza se responde: "en qué jornadas el motor difirió del template y quién ganó" |
| AC-WP003-008 | REQ-F-008 | Una corrida interrumpida en la jornada N se reanuda desde N sin recomputar 1..N-1 |

## Verificación

```bash
python -m mova_fpl.cli.backtest --season 2025-26 --mode anonymized --seed 42
python -m mova_fpl.cli.backtest --season 2025-26 --mode anonymized --seed 42   # idéntica
pytest tests/test_decide_identity.py tests/test_replay_no_future_access.py \
       tests/test_trace_reproducibility.py -v
```

## Evidencia requerida

| Criterio | Tipo | Evidencia esperada |
| --- | --- | --- |
| AC-WP003-001 | reporte | `RunReport` con puntos por jornada y acumulados |
| AC-WP003-002 | test | pytest `test_replay_no_future_access.py` |
| AC-WP003-003 | reporte | `RunReport`: jornada 1 resuelta en cold start sin excepción |
| AC-WP003-004 | reporte | Tabla de los tres baselines dentro del `RunReport` |
| AC-WP003-005 | test | pytest `test_decide_identity.py` |
| AC-WP003-006 | test | pytest `test_trace_reproducibility.py` más diff de dos corridas |
| AC-WP003-007 | consulta | Query de traza y su resultado |
| AC-WP003-008 | test | pytest — reanudación desde la jornada N |

## Rollback

Borrar `mova_fpl/engine/`, `mova_fpl/trace/` y `data/processed/trace.db`.

## Resultado de ejecución — 2026-08-07

**8/8 criterios en `pass`.** 332 pruebas verdes en la suite completa.

Backtest ciego 2025/26, 38 jornadas, política stub:

| Serie | Puntos | vs motor |
|---|---:|---:|
| **Motor (greedy-stub)** | **1.302** | — |
| template | 2.043 | −741 |
| aleatorio | 533 | +769 |
| techo (información perfecta) | 5.871 | −4.569 |

Captura del techo: **22,2%**. El motor gana 2 de 38 jornadas contra el template.
**Es un piso, no un logro**: la política es deliberadamente tonta y el número existe
para que WP-004 y WP-005 tengan contra qué medirse.

Cinco bugs encontrados y corregidos durante la ejecución, detallados en
[`evidence/WP-003-backtest-2025-26.md`](../evidence/WP-003-backtest-2025-26.md).

## Definition of Done

- [ ] Todos los criterios requeridos tienen evidencia `pass`.
- [ ] El número del stub queda publicado como piso — no como logro.
- [ ] Los baselines quedan medidos y disponibles para los workpacks siguientes.

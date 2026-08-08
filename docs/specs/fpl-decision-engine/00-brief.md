---
type: project
name: "Motor de decision FPL 2026/27 - modelos, reglas y harness de backtest blind — Brief"
created: 2026-08-07
updated: 2026-08-07
tags: [spec-driven, architecture, fpl-decision-engine, mova]
status: draft
---

# Motor de decisión FPL 2026/27 — Brief

## Objetivo

Construir un motor determinista capaz de **emitir una decisión de plantilla, alineación
y capitán para cada gameweek de la Fantasy Premier League 2026/27**, y probar su calidad
con un **backtest walk-forward ciego sobre la temporada 2025/26** antes de operar en vivo.

Resultado observable, en dos partes:

1. **GW1 (viernes 21 de agosto de 2026, 17:30 UTC / 12:30 Bogotá):** el motor produce un
   acta con 15 jugadores válidos bajo £100M, 11 titulares, capitán y vicecapitán, dentro
   del deadline oficial.
2. **Antes de esa fecha:** el mismo código de decisión, corrido sobre las 38 jornadas de
   2025/26 en modo ciego con reentrenamiento progresivo, produce un puntaje reproducible
   comparable contra baselines explícitos.

La segunda parte no es un experimento paralelo: **es la evidencia de que la primera
funciona**. Ambas invocan la misma función `decide(gw, state)`.

## Contexto

### Hechos verificados

Todos verificados por inspección directa el 2026-08-07.

| # | Hecho | Fuente |
| --- | --- | --- |
| H-01 | La temporada 2026/27 arranca con deadline de GW1 el `2026-08-21T17:30:00Z`; el bootstrap tiene 38 eventos y 572 jugadores | `data/raw/fpl/bootstrap_static.json` |
| H-02 | El bootstrap 2026/27 ya expone `defensive_contribution` y `defensive_contribution_per_90` (105 campos por jugador) | `data/raw/fpl/bootstrap_static.json` |
| H-03 | Reglas 2026/27: BPS reformado (CBI pasa a 1 BPS por cada 3, antes 1 por cada 2; se elimina "atajada fuera del área"; se agrega +1 BPS por atajar big chance; penalti atajado baja de +8 a +7 BPS). DefCon sin cambios: 10 CBIT para DEF, 12 CBIRT para MID/FWD, tope +2 pts | [premierleague.com](https://www.premierleague.com/en/news/4679946/whats-new-in-202627-fantasy-changes-to-bonus-points-system) |
| H-04 | `fpl_historical_multi_season` tiene 224.143 filas, 9 temporadas (2016-17 → 2024-25), 38 GWs cada una, 620–865 jugadores por temporada | `data/mundial.db` |
| H-05 | Cobertura por bloque: 2016-17→2018-19 (68K) tiene CBI/tackles/recoveries pero no xG; 2019-20→2021-22 (72K) no tiene ninguno; 2022-23→2024-25 (84K) tiene xG pero no columnas defensivas | `data/mundial.db`, conteo de no-nulos por temporada |
| H-06 | `merged_gw.csv` de 2025-26 en el repo vaastav tiene **29.757 filas, 841 jugadores, 38 GWs, 46 columnas**, e incluye `defensive_contribution` (9.725 filas >0, máx 29), `clearances_blocks_interceptions`, `recoveries`, `tackles`, `expected_goals`, `bps` y `value` | descargado y verificado |
| H-07 | `defensive_contribution` viene como **conteo crudo de acciones**, no como puntos ya calculados (ej. Reinildo GW1: 8 acciones en 90 min → bajo el umbral de 10) | inspección del CSV |
| H-08 | La tabla local `fpl_player_history` sólo tiene 1.499 filas / 50 jugadores / GW1–30 — es un pull parcial de 2025/26 | `data/mundial.db` |
| H-09 | `events` tiene 444.252 eventos Opta de **Premier League 2025-26** en 291 partidos (de 380), y 163.678 del Mundial en 104 partidos | `data/mundial.db` |
| H-10 | Los tipos de evento necesarios para reconstruir CBIT existen: Clearance 16.401, Tackle 9.815, Interception 4.812, BlockedPass 4.270, BallRecovery 23.544 | `data/mundial.db` |
| H-11 | El código legacy tiene leakage estructural: el CTE `opta_agg` agrega eventos por jugador **sin filtro temporal**, y las features usan `now_cost` (precio de cierre) en vez de `ph.value` (precio de la jornada) | `src/mova_model/fpl_xp.py` |
| H-12 | `solve_transfers` no es MILP: es búsqueda voraz de 5 peores × 15 mejores, una transferencia, misma posición, presupuesto fijo en £100M | `src/mova_model/fpl_optimizer.py` |
| H-13 | El "FPL Gym Environment" citado en el alcance del proyecto no existe en el código | grep sobre `src/` y `scripts/` |
| H-14 | Los docs 16–20 y los reportes de `outputs/` afirman resultados mutuamente inconsistentes (v3 con MAE 2.026 vs 2.81; proyecciones de 2.001 / 2.162 / 2.167 / 2.491 / 2.566 pts) | `docs/`, `outputs/` |
| H-15 | `betting.db` tiene 195.623 partidos de club en 17 ligas desde 1993 con cuotas | `data/betting.db` |
| H-16 | Las **dobles jornadas** son reales y frecuentes: 9.114 pares jugador-gameweek con dos partidos a lo largo de las 10 temporadas (2.217 sólo en 2021-22). Verificado con Raya en 2025-26 GW26, fixtures 252 y 310 | ingesta WP-001 |
| H-17 | La temporada **2019-20 (COVID)** numera gameweeks hasta la **47** en el origen: 6.004 filas por encima de la 38 | ingesta WP-001 |
| H-18 | El CSV de 2025-26 trae 10 filas byte-idénticas duplicadas; es un artefacto del origen | ingesta WP-001 |
| H-19 | El motor de reglas reproduce **el 100,000%** de las 29.747 actuaciones de 2025/26 (`total_points` recomputado desde estadísticas crudas), cero discrepancias | golden test WP-002 |
| H-20 | La única diferencia entre las reglas 2025/26 y 2026/27 son **cuatro parámetros del BPS**. La matriz de puntuación base, los umbrales de DefCon, la composición de plantilla y los chips son idénticos | diff WP-002 |
| H-21 | El dinero debe manejarse en **décimas enteras**: en float, `95.8 + 4.2 = 100.00000000000001` supera el presupuesto y rechaza plantillas válidas | backtest WP-003 |
| H-22 | Las **jornadas en blanco** existen: un jugador cuyo equipo no juega no tiene fila en el catálogo pero sigue en la plantilla y puntúa 0 | backtest WP-003 |
| H-23 | El **precio correlaciona 0,32** con los puntos de la GW1 de 2025/26. Es información pre-deadline y el mejor prior disponible en cold start | backtest WP-003 |
| H-25 | El campo `element` de FPL **se reasigna cada temporada**: el elemento 1 es Ospina en 2016-17 y Raya en 2025-26. Agrupar historial por `element` entre temporadas empalma jugadores distintos | WP-004 |
| H-26 | El formato de `name` cambió tres veces (`David_Ospina` → `Petr_Cech_1` → `David Raya Martín`). Las transiciones 2017-18→2018-19 y 2019-20→2020-21 compartían **cero** jugadores; con `player_key` normalizado comparten 418 y 451 | WP-004 |
| H-27 | La brecha de **política** (−633 pts) es seis veces la de **proyección** (−108 pts frente al template). El límite de una transferencia por jornada con horizonte 1 domina el resultado | WP-004 |
| H-24 | El promedio real del mánager (`average_entry_score`) **no está** en el dataset histórico de vaastav; sólo se expone en el bootstrap de la temporada en curso | baselines WP-003 |

### Inferencias

| # | Inferencia | Base |
| --- | --- | --- |
| I-01 | DefCon sólo es modelable con datos de 2025/26, porque es la primera temporada con la regla | H-03, H-05, H-06 |
| I-02 | Los 444K eventos Opta corresponden a ~77% de la temporada 2025/26 (291 de 380 partidos) | H-09 |
| I-03 | Recalcular BPS bajo reglas 2026/27 requiere componentes que el CSV de vaastav no trae (atajadas dentro/fuera del área, big chances); haría falta derivarlos de los eventos Opta | H-03, H-06 |
| I-04 | Los resultados publicados en docs 16–20 no son reproducibles ni comparables entre sí; se tratan como no-evidencia | H-11, H-12, H-14 |
| I-05 | Modelar bien P(DefCon ≥ umbral) es una ventaja competitiva porque la regla es nueva y el mercado de managers aún la está incorporando; predecir goles no da ventaja porque ya lo hacen todos | H-03, H-07 |

### Preguntas abiertas

| # | Pregunta | ¿Bloquea? | Owner |
| --- | --- | --- | --- |
| Q-01 | ¿Cuál es el `entry_id` del equipo FPL 2026/27 de Julián, para leer estado real (banco, FTs, chips) en producción? | **Sí para WP-007**; no para el resto | Julián |
| Q-02 | ¿Objetivo declarado de la temporada: rank global, mini-liga específica, o ambos? Define la función objetivo (maximizar puntos vs maximizar rank ajustado por ownership) | **Sí para WP-006** | Julián |
| Q-03 | ¿Se completan los 89 partidos Opta faltantes de 2025/26 antes de GW1? | No — sólo afecta el stretch de BPS 2026/27 | Julián |
| Q-04 | ¿Se acepta que la política de chips en v1 sea heurística y no optimizada? | No — asumido `sí` en este brief | Julián |

## Actores y necesidades

| Actor | Necesidad | Resultado esperado |
| --- | --- | --- |
| Julián (operador) | Recibir una decisión accionable y justificada antes de cada deadline | Acta en Markdown con 15+11+C, costo, xP y razón por jugador |
| Julián (sponsor) | Saber si el motor sirve **antes** de arriesgar la temporada | Número del backtest 2025/26 vs baselines, reproducible |
| Julián (arquitecto) | Que el sistema sea modular y no repita el Frankenstein anterior | Fronteras explícitas: `rules` sin datos, `models` sin reglas, `engine` sin saber si es 2018 o hoy |
| Iniciativa sucesora (agente LLM) | Un motor determinista medible contra el cual justificar su existencia | `decide()` estable + traza + baselines |

## Alcance

Dentro de esta iniciativa:

1. **Rama limpia** `feat/fpl-agent-clean` y paquete nuevo `mova_fpl/`, sin dependencia de
   `src/mova_data/` ni `src/mova_model/`.
2. **Almacén canónico** de 10 temporadas (2016-17 → 2025-26) en un esquema único.
3. **Contrato `as_of`**: única vía de lectura de datos, que hace el leakage temporal
   estructuralmente imposible.
4. **Motor de reglas versionado por temporada** (`2025_26` y `2026_27`): puntuación con
   DefCon y BPS, composición de plantilla, formaciones, cuota por club, precios y banco,
   transferencias libres, sustituciones automáticas y chips.
5. **Modelo de minutos**: clasificador {0, 1–59, 60+}.
6. **Modelo de puntos descompuesto** por componente, incluyendo P(DefCon ≥ umbral).
7. **Optimizador** de plantilla, XI y capitán con horizonte rodante multi-gameweek.
8. **Harness `replay()`** walk-forward ciego sobre 2025/26, con reentrenamiento progresivo
   y baselines obligatorios.
9. **Traza persistente** de cada decisión y sus insumos.
10. **Acta de decisión** para GW1 de 2026/27.

## Fuera de alcance

Explícitamente **no** forman parte de v1:

| Fuera | Por qué | Dónde va |
| --- | --- | --- |
| **Agente LLM y sus tools** | Necesita un motor determinista medible como baseline; sin eso no se puede saber si aporta | Iniciativa sucesora, post-GW1 |
| **Escritura automática a la API de FPL** | Elimina toda una clase de riesgo operativo en 14 días. v1 emite acta; Julián la ingresa | Iniciativa sucesora |
| **Búsqueda web de lesiones, ruedas de prensa y foros** | Es una tool del agente, no del motor determinista | Iniciativa sucesora |
| **Comparativa multi-agente con modelos de OpenRouter** | Requiere el agente y el harness estabilizado | Iniciativa sucesora |
| **Cron / servicio desplegado** | v1 corre por CLI local. La arquitectura queda preparada (`decide()` sin estado global), pero desplegar no cabe | Post-GW1 |
| **Recompute completo de BPS bajo reglas 2026/27 desde eventos Opta** | Faltan componentes (big chances, atajadas por zona) y sólo hay 291/380 partidos | Stretch, no bloquea |
| **Apuestas y odds como feature del motor FPL** | `betting.db` sirve al modelo de partido para clean sheets; usarlo como señal de FPL no está probado | Fuera |
| **Refactor o mantenimiento de `mova_data` / `mova_model`** | Se congelan como legacy de sólo lectura | Se marcan deprecados |
| **Optimización de la política de chips** | v1 implementa las reglas de chips y los simula, pero decide su uso con heurística simple | Iniciativa sucesora |
| **Migración de la traza a Postgres** | SQLite alcanza mientras haya un solo agente | Cuando haya multi-agente |

## Métricas de éxito

| Métrica | Baseline | Objetivo | Método de medición |
| --- | --- | --- | --- |
| M-01 Acta de GW1 emitida a tiempo y válida | n/a | 1 acta, 0 violaciones de restricción, antes del `2026-08-21T17:30:00Z` | Timestamp del archivo + validador de reglas |
| M-02 Fidelidad del motor de reglas | n/a | ≥ 99% de 29.757 filas de 2025/26 con puntos recomputados == `total_points` | `pytest` sobre el CSV completo |
| M-03 Features con dependencia futura | ≥ 2 en el código legacy (H-11) | **0** | Test de contrato: `as_of(T)` nunca devuelve fila con GW ≥ T |
| M-04 Backtest blind 2025/26 vs baseline template | Por medir en WP-003 | ≥ template | `replay("2025-26", blind)` |
| M-05 Calibración del modelo de minutos | Por medir en WP-004 | Brier y ECE reportados; ECE ≤ 0.05 en P(60+) | Held-out por temporada |
| M-06 Reproducibilidad | n/a | Misma semilla + mismo git sha → resultado idéntico | Doble corrida en CI local |
| M-07 Latencia del ciclo de decisión | n/a | ≤ 10 min por gameweek en portátil | `time` sobre `decide()` |

> M-04 y M-05 no tienen baseline hoy **a propósito**: medirlos es el entregable de sus
> workpacks. Declarar un número inventado sería repetir el error de los docs 16–20.

## Restricciones

- **Deadline duro no negociable:** `2026-08-21T17:30:00Z`. Lo fija la Premier League.
- **14 días calendario** desde 2026-08-07.
- Python vía conda (`/home/jzuluaga/miniconda3/bin/python3`, 3.13.5).
- Sólo fuentes públicas y gratuitas: API de FPL, repo `vaastav/Fantasy-Premier-League`,
  y los eventos Opta ya recolectados.
- Trabajo en rama `feat/fpl-agent-clean`. No se toca `main`.
- Sin PII, sin datos de clientes, sin credenciales en el repo.
- Los 1.8 GB de `data/` no se mueven: el paquete nuevo los lee donde están.

## Supuestos

| # | Supuesto | Si falla |
| --- | --- | --- |
| S-01 | `vaastav/Fantasy-Premier-League` sigue publicando 2026-27 semanalmente durante la temporada | Se cae a la API oficial de FPL, que expone la GW en curso |
| S-02 | La API de FPL sigue sirviendo `bootstrap-static` y `fixtures` sin autenticación | Bloquea producción; habría que scrapear |
| S-03 | Julián tiene o creará equipo FPL 2026/27 antes del deadline | M-01 no se puede cumplir |
| S-04 | Las reglas 2026/27 publicadas no cambian antes de GW1 | Se versiona `rules/2026_27.py` y se revalida el golden test |
| S-05 | 2025/26 es representativa de 2026/27 para entrenar (mismo régimen DefCon, BPS distinto) | El backtest sobreestima; se documenta como sesgo conocido |

## Aprobaciones

Julián es el aprobador único de esta iniciativa: alcance, arquitectura y riesgo.

| Área | Responsable | Estado | Fecha |
| --- | --- | --- | --- |
| Intención, alcance y arquitectura | Julián Zuluaga | **approved** | 2026-08-07 |

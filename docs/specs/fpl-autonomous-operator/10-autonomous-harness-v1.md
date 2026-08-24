---
type: project
name: "MOVA FPL — Autonomous Harness v1"
created: 2026-08-23
updated: 2026-08-23
tags: [mova, fpl, autonomy, postgres, agents, observability, continuous-improvement]
status: active-design
---

# Autonomous Harness v1

## 1. Resultado buscado

MOVA debe operar una temporada completa sin intervención rutinaria y, al mismo tiempo,
seguir siendo comprensible y manipulable por ORBIX. Para cualquier jornada, ORBIX debe
poder:

- conocer el estado real del collector, datos, modelos, equipo, research y ciclo;
- ejecutar o reintentar un paso sin repetir los demás;
- explicar qué entradas y versiones produjeron una decisión;
- estimar costo, calidad, riesgo y frescura;
- comparar una decisión con su contrafactual;
- diagnosticar y refactorizar el harness desde el repo;
- proponer, probar, promover o revertir una mejora con evidencia.

La autonomía operativa puede llegar a `A3`. La auto-modificación irrestricta no es un
objetivo: los cambios de código, schema, modelos y guardrails pasan por experimentos y
gates de promoción.

Este documento es la hoja de ruta ejecutable. Las specs 08 y 09 quedan como referencias de
hardening para cuando un riesgo real exija mayor aislamiento; no son el backlog del MVP.

## 2. Baseline confirmado — 23 de agosto de 2026

Ya existe y se conserva:

- engine/modelos FPL vivos bajo `mova_fpl/`, con MILP y horizonte rodante;
- almacén histórico canónico de 253.890 filas y 10 temporadas;
- collector oficial con snapshots sellados y cadencia por fase;
- estado privado autenticado con equipo, banco, transferencias y chips;
- control plane Docker + systemd en el VPS;
- `ops.db`, auditoría, jobs, health, incidentes, API local y backups;
- browser persistente aislado y operable por CDP;
- controles `shadow`, `A0`, `kill_switch=true`, `browser_writes=false`;
- contratos de intervención y backtest pareado del agente.

La base de desarrollo también quedó saneada antes de iniciar el harness:

- `main` contiene solo el producto FPL; legado y binarios quedaron en el tag
  `archive/pre-harness-cleanup-2026-08-23`;
- `AGENTS.md`, `pyproject.toml`, CLI instalable y CI definen una entrada reproducible;
- `pytest -q` es hermético y las pruebas con datos externos están marcadas explícitamente;
- un contrato de higiene bloquea carpetas legacy y artefactos pesados en Git.

Verificación viva del corte:

- API healthy, cinco timers activos y cero incidentes abiertos;
- GW2, deadline oficial `2026-08-28T17:30:00Z`;
- último team state válido: 15 jugadores, 1 FT, banco £0.0m y chips disponibles;
- último tick completado y correctamente omitido por cadencia;
- runtime engine `684e5da`; checkout documental del VPS `d5e9d25`;
- `main` contiene la investigación de harness hasta `4ead0e1`.

Gaps reales:

1. datos, control plane y memoria están repartidos entre SQLite y artefactos;
2. no existe una interfaz completa y estable para operar todo el sistema;
3. research/noticias no está conectado de punta a punta;
4. no existe todavía un ciclo multirol de estrategia, crítica y revisión;
5. el reviewer post-GW y la promoción de mejoras no están implementados;
6. costos y calidad no se pueden consultar como una sola scorecard;
7. el browser sabe leer, pero la ejecución autónoma sigue bloqueada.

## 3. Decisiones de arquitectura

### 3.1 Un orquestador, varios roles

El scheduler y la máquina de estados son código determinista. Los roles LLM son jobs
acotados, no procesos residentes ni agentes libres que se delegan tareas.

Roles iniciales:

| Rol | Responsabilidad | No puede |
| --- | --- | --- |
| Researcher | fuentes, lesiones, sanciones, roles y contexto | elegir equipo o ejecutar |
| Strategist | interpretar modelo, research y plan de temporada | saltarse MILP o reglas |
| Critic | buscar riesgos, contradicciones y alternativas | modificar la propuesta |
| Validator | combinar reglas duras y reporte crítico | inventar datos faltantes |
| Executor | aplicar un `DecisionEnvelope` aprobado | rediseñar la decisión |
| Reviewer | atribución post-GW y propuestas de mejora | promover cambios solo |

Un solo proveedor/modelo puede servir varios roles inicialmente. Separar servicios o
modelos se hace únicamente si costo, calidad o aislamiento lo justifican.

### 3.2 PostgreSQL como núcleo durable del VPS

Se desplegará un PostgreSQL local al VPS para datos analíticos, estado, memoria y ledger.
Supabase continúa siendo exclusivamente PM del proyecto.

Los artefactos pesados —modelos, HTML autorizado, manifests, reportes y capturas— permanecen
en un volumen versionado. PostgreSQL guarda metadata, relaciones, hashes y resultados
consultables.

La migración no es big bang:

1. crear PostgreSQL, migrations y backups sin tocar el runtime actual;
2. importar histórico y ledger SQLite en shadow;
3. comparar conteos, hashes, queries y decisiones en ambos stores;
4. cambiar el repository adapter a PostgreSQL;
5. conservar SQLite read-only como rollback durante tres ciclos;
6. retirar el writer SQLite después de un restore drill aprobado.

### 3.3 Una imagen de aplicación, browser separado

Stack inicial:

1. `postgres` — datos y control plane;
2. `mova-app` — API, collector, modelos, scheduler y roles agénticos;
3. `mova-browser` — sesión FPL y ejecución UI;
4. volumen `artifacts` y destino de backups.

No habrá un contenedor por agente. Los jobs agénticos corren one-shot dentro de
`mova-app`; Codex puede permanecer como especialista opcional invocado por ORBIX.

## 4. Capas funcionales

```mermaid
flowchart LR
  timer["systemd tick"] --> coordinator["Cycle Coordinator"]
  coordinator --> collector["Collectors"]
  collector --> pg[(PostgreSQL)]
  coordinator --> models["Models + MILP"]
  models --> pg
  coordinator --> research["Researcher"]
  research --> pg
  coordinator --> strategy["Strategist"]
  strategy --> critic["Critic + Validator"]
  critic --> decision["DecisionEnvelope"]
  decision --> executor["Browser Executor"]
  executor --> verify["Post-action verify"]
  verify --> pg
  coordinator --> reviewer["GW Reviewer"]
  reviewer --> improve["Change proposal"]
  improve --> evals["Backtest + shadow + promotion gate"]
```

### 4.1 Datos y collector

- API pública, fixtures, histórico y estado privado tienen adapters separados;
- toda captura lleva `observed_at`, cutoff, source, hash, calidad y artifact ref;
- el tick evalúa cada quince minutos, pero cada collector usa cadencia por fuente y fase;
- no-cambio se registra como observación fresca sin recomputar modelos;
- schema drift, stale data, cobertura anómala o temporada incorrecta abren incidente;
- entrenamiento e inferencia son jobs distintos.

### 4.2 Analítica y modelos

Cada modelo expone contratos comunes:

- `train(dataset_release, config) -> model_release`;
- `predict(model_release, cycle_manifest) -> projection_run`;
- `explain(projection_run, subject) -> explanation`;
- `evaluate(model_release, dataset_release) -> scorecard`.

El agente puede accionar y leer estos contratos, pero no alterar predicciones en memoria.
Toda intervención entra como input versionado y se mide con/sin intervención.

### 4.3 Estado del juego y estrategia

El estado actual debe resolver en una consulta:

- plantilla, XI, banca, C/V, precio de compra/venta y banco;
- transfers libres, hits y transfers ya realizados;
- chips disponibles, gastados y ventanas;
- deadline, fase y última verificación;
- plan de temporada y plan vigente de 3–8 GWs.

La estrategia usa horizonte rodante: conserva un plan, lo compara con nueva evidencia y
explica por qué se mantiene o revisa. No reoptimiza la filosofía completa en cada tick.

### 4.4 Research con evidencia

Flujo mínimo:

`search → URL candidata → fetch seguro → documento sellado → señal → conflicto/TTL`.

El Researcher produce un acta, no una decisión. Cada señal material conserva fuente,
fecha, locator, entidad, confianza, expiración y estado de validación. Las specs 08–10 y
los schemas existentes se reutilizan solo donde aporten control real.

### 4.5 Decisión, crítica y validación

El Strategist recibe un `CycleManifest` sellado con datos, predicciones, equipo, plan,
research y memoria aceptada. Devuelve opciones y tradeoffs. El MILP sigue armando las
plantillas legales.

El Validator exige:

- datos y team state frescos;
- presupuesto, posiciones, clubes y transfer cost válidos;
- capitán, banca y chip coherentes;
- conflictos de research resueltos o explícitamente bloqueados;
- comparación contra `do_nothing` y alternativa principal;
- consistencia con el horizonte y el plan de temporada;
- hard stop, autonomía y costo dentro de policy.

### 4.6 Ejecución y verificación

El Executor recibe un `DecisionEnvelope` inmutable. Relee el estado antes de actuar,
calcula el diff exacto, aplica una vez y vuelve a leer después de guardar. Una notificación
de éxito sin estado post-acción coincidente es fallo.

Acciones por riesgo:

| Clase | Ejemplo | Política inicial | Target |
| --- | --- | --- | --- |
| R0 | leer/diagnosticar | autónoma | autónoma |
| R1 | research, modelos, propuestas | autónoma | autónoma |
| R2 | XI, banca, C/V reversibles antes del deadline | shadow/supervisada | A2 |
| R3 | transfer, hit o chip | aprobación | A3 tras gates |

## 5. PostgreSQL y artefactos

Schemas y tablas mínimas:

| Schema | Tablas núcleo |
| --- | --- |
| `raw` | `ingestion_runs`, `source_snapshots` |
| `analytics` | `player_gameweek`, `fixtures`, `dataset_releases`, `model_runs`, `predictions` |
| `game` | `cycles`, `team_snapshots`, `season_plans` |
| `research` | `runs`, `documents`, `signals` |
| `agent` | `runs`, `decision_records`, `validations`, `executions`, `gw_reviews`, `lessons`, `change_proposals` |
| `ops` | `job_runs`, `job_steps`, `controls`, `events`, `incidents`, `cost_ledger` |

Reglas:

- una migración versionada crea o cambia schema;
- `as_of` y cutoff se validan también al leer;
- append-only para decisiones, ejecuciones, reviews y controles;
- JSONB solo para payloads variables; entidades consultadas frecuentemente son columnas;
- logs completos rotan en disco; PostgreSQL conserva eventos y resúmenes, no cada línea;
- artifacts se publican por rename y hash, y se respaldan junto con PostgreSQL;
- ningún secreto, cookie o chain-of-thought entra en DB, artifacts o logs.

## 6. Memoria y mejora continua

La memoria no es historial de chat. Tiene cinco tipos explícitos:

| Memoria | Contenido | Promoción |
| --- | --- | --- |
| `season_plan` | chips, horizonte, riesgo y objetivos | nueva versión aprobada por policy |
| `decision_record` | qué se decidió, alternativas y por qué | automática por ciclo válido |
| `gw_review` | predicción vs resultado y atribución | automática post-settlement |
| `lesson` | aprendizaje reusable con evidencia | propuesta → validación |
| `change_proposal` | cambio de prompt/config/modelo/código/schema | experimento → shadow → promote |

El Reviewer separa causa probable:

- datos/frescura;
- modelo/calibración;
- optimización/constraints;
- research/contexto;
- estrategia/horizonte;
- ejecución/verificación;
- azar no accionable.

Nunca optimiza retrospectivamente contra un solo GW. Una propuesta necesita dataset,
baseline, métrica, costo, riesgo, resultado y criterio de rollback.

Niveles de cambio:

- `C0`: observación o documentación; auto-registrable;
- `C1`: prompt/config/fuente; puede probarse automáticamente en shadow;
- `C2`: modelo o código; branch/patch, tests y backtest, revisión antes de promover;
- `C3`: schema, guardrail o autonomía; aprobación explícita y restore/rollback drill.

## 7. Superficie de operación para ORBIX

Un único CLI estable, con salida humana y `--json`:

```text
mova status [--json]
mova doctor [--json] [--no-network]
mova collect [public|private|all] [--force --reason ...]
mova data inspect|freshness|coverage
mova model train|predict|explain|score
mova research run|inspect
mova cycle run|resume|inspect
mova decision inspect|compare|validate
mova execute preflight|apply|verify
mova review gw|season
mova improve propose|test|promote|rollback
mova cost report [--gw N|--month YYYY-MM]
mova logs|incidents|controls
mova backup create|verify|restore-drill
```

Cada mutación exige `actor`, `reason`, idempotency key y modo efectivo. Los comandos
destructivos o de ejecución muestran diff y policy antes de actuar.

Se crea la skill `mova-fpl-operator` como manual operativo de ORBIX. Debe explicar:

- arquitectura viva y fuentes de verdad;
- comandos y contratos JSON;
- cómo consultar Postgres sin saltarse repositories;
- cómo leer modelos, decisiones, costos y scorecards;
- diagnóstico por síntomas;
- proceso de cambio, tests, deploy y rollback;
- qué nunca debe ejecutarse automáticamente.

La skill no duplica la spec: referencia comandos versionados y runbooks cercanos al código.

## 8. Observabilidad, calidad y costos

`mova status` resume un único estado:

- próximo deadline y fase;
- edad/calidad de cada fuente;
- último dataset/modelo/predicción;
- team state y fingerprint;
- research coverage/conflicts;
- decisión y validación;
- ejecución/verificación;
- jobs fallidos, incidentes y controles;
- costo del GW y presupuesto restante.

Scorecard del harness por GW:

| Dimensión | Ejemplos |
| --- | --- |
| Reliability | jobs a tiempo, retries, incidentes, recuperación |
| Data | frescura, cobertura, drift, causalidad |
| Models | calibración, error y drift por componente |
| Research | cobertura, evidencia, conflictos y utilidad atribuida |
| Decisions | validez, regret vs alternativas y coherencia de horizonte |
| Execution | diff correcto, persistencia y duplicados |
| Cost | provider, tokens, search, CPU/duración y storage |

`ops.cost_ledger` registra provider/modelo, tokens, búsquedas, costo conocido/estimado,
duración y categoría. Hay budgets por job, GW y mes. El PostgreSQL usa el VPS existente:
no añade un proveedor pago, pero sí reserva inicialmente 0,5–0,8 GB RAM y 1–2 GB de disco.
Los costos variables de LLM/search se miden antes de fijar un techo; Codex por suscripción
se reporta como cuota/uso, no como costo ficticio por token.

## 9. Ciclo autónomo

```text
observe
  → collect
  → qualify data
  → predict
  → research
  → propose
  → critic + validate
  → freeze
  → preflight
  → execute if policy permits
  → verify
  → settle
  → review
  → propose improvements
```

El tick descubre trabajos vencidos; no ejecuta el ciclo completo cada quince minutos. Cada
paso es idempotente, reanudable y tiene input/output hash. Un fallo detiene dependientes,
no borra evidencia previa y nunca amplía autonomía.

## 10. Roadmap implementable

| Workstream | Entrega | Estimación | Dependencia |
| --- | --- | ---: | --- |
| HV1-00 ✅ | reset del repo, archivo de legado, packaging y CI hermético | completado | baseline actual |
| HV1-01 ✅ | contrato `mova`, status/doctor y skill del operador | completado | HV1-00 |
| HV1-02 🟡 | PostgreSQL shadow, import y verificación; luego adapter/cutover | 10–14 h | HV1-01 |
| HV1-03a ✅ | collector/data quality autónomo | completado | HV1-02 |
| HV1-03b | interfaz uniforme de modelos | 4–6 h | HV1-03a |
| HV1-04 | team state, season plan y memoria explícita | 6–8 h | HV1-02 |
| HV1-05 | research con evidencia y acta | 8–12 h | HV1-02/03 |
| HV1-06 | Strategist + Critic + Validator + DecisionEnvelope | 10–14 h | HV1-03/04/05 |
| HV1-07 | executor/verifier y autonomía por riesgo | 8–12 h | HV1-06 |
| HV1-08 | reviewer, scorecard, costos y promoción de mejoras | 8–12 h | HV1-03/06 |

No es necesario completar 64–92 horas antes de obtener valor. Cortes de entrega:

1. **Operable** — HV1-01: ORBIX entiende y acciona lo existente;
2. **Consolidado** — HV1-02..04: una fuente durable y memoria explícita;
3. **Strategic shadow** — HV1-05..06: actas, opciones y validación multirol;
4. **Guarded execution** — HV1-07: browser verificable según riesgo;
5. **Learning system** — HV1-08: scorecard y mejora continua controlada.

## 11. Definition of Done del harness v1

- un ciclo completo puede ejecutarse, reanudarse y explicarse desde `mova`;
- Postgres y artifacts reconstruyen toda decisión sin depender de Supabase;
- collector, modelos, research y team state tienen health/freshness explícitos;
- cada decisión tiene alternativas, validación, plan de horizonte y costo;
- cada acción tiene preflight, diff, post-read y evidencia;
- cada GW produce review y atribución pareada;
- una mejora puede recorrer proposal → test → shadow → promote/rollback;
- ORBIX puede diagnosticar, puntuar y refactorizar usando la skill y el repo;
- tres rehearsals/GWs pasan sin duplicados ni evidencia faltante;
- la autonomía máxima se activa por clase de riesgo, no por confianza subjetiva.

## 12. No objetivos inmediatos

- LangGraph, handoffs libres o agentes residentes;
- vector DB para memoria;
- Kafka, Redis, Kubernetes, Loki o un data lake;
- un contenedor por rol;
- migrar logs crudos completos a PostgreSQL;
- cambiar el equipo mientras el sistema permanezca en `A0`;
- permitir que el Reviewer modifique producción sin evaluación.

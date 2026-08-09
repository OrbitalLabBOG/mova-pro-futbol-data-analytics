# CLAUDE.md — mova-pro-futbol-data-analytics

Repositorio de analítica de fútbol de la vertical **MOVA**. Hoy su parte viva es el
**motor de decisión de Fantasy Premier League**: un sistema que lee el estado público de
la liga, proyecta puntos esperados por jugador y emite un **acta de decisión** —qué once,
qué capitán, qué transferencias— antes del cierre de cada jornada.

> **Contexto de negocio:** proyecto "MOVA Pro Fútbol Data Analytics"
> (`cbd36dc4-0c1a-45ad-9134-1019e99639e4`). Consultar con `/proyecto mova pro` desde
> orbital-os — alcance, estado y tareas NO están duplicados aquí.

## Lo primero que hay que saber

**El repo contiene dos cuerpos de código y solo uno está vivo.**

| | Vivo | Congelado |
|---|---|---|
| Paquete | `mova_fpl/` | `src/mova_data/`, `src/mova_model/`, `scripts/` |
| Qué es | Motor FPL v1, escrito de cero bajo spec | Mundial 2026, apuestas/CLV y el intento previo de FPL |
| Se puede tocar | Sí | **No**. Se conserva como registro, no como base |

El código legacy de FPL (`src/mova_model/fpl_xp.py`, `scripts/live_agent_runner.py`,
`scripts/train_fpl_xp_v*.py`) tiene **leakage estructural** y reporta números que no son
reproducibles. Está congelado a propósito. No importarlo, no extenderlo, no citar sus
resultados. `tests/test_architecture_boundaries.py` impide que `mova_fpl` lo importe.

La rama viva es **`feat/fpl-agent-clean`**, no `main`.

## Stack

- Python **3.13.5** vía conda: `/home/jzuluaga/miniconda3/bin/python3`
- pandas 2.3.3 · numpy 2.4.3 · scipy 1.16.3 · scikit-learn 1.7.2 · **PuLP 3.3.2** (CBC) · joblib 1.5.2
- Almacenamiento: **SQLite**. Nada de servidor, nada de credenciales.
  - `data/processed/fpl_canonical.db` — 253.890 filas, 10 temporadas (2016-17 … 2025-26), 61 columnas
  - `data/processed/trace.db` — traza de corridas y decisiones
- Sin deploy. Corre en local, a mano, antes de cada deadline. No hay cron todavía.

## Cómo correr

```bash
cd ~/code/orbital-lab/mova-pro-futbol-data-analytics

# 1. almacén canónico (idempotente; ~2 min la primera vez)
python -m mova_fpl.data.ingest --all

# 2. modelos (los .joblib no están en Git, se regeneran; ~2 min)
python -m mova_fpl.cli.train_minutes --holdout 2025-26
python -m mova_fpl.cli.train_points  --holdout 2025-26

# 3. decisión en vivo → outputs/fpl/<temporada>/gwNN_decision.md  (~6 s)
python -m mova_fpl.cli.live --season 2026-27 --gw 1 --horizon 3 --top-k 0
#    desde la GW2, con equipo real y chips:
FPL_TEAM_ID=<id> python -m mova_fpl.cli.live --season 2026-27 --gw 2 --horizon 3 \
    --top-k 0 --chips

# 4. backtest ciego de una temporada completa (~2 min)
python -m mova_fpl.cli.backtest --season 2025-26 --policy milp --projector points --horizon 3

# pruebas
pytest -q            # 524 verdes
pytest -m slow -q    # 2 más: temporada completa, ~3 min
```

El runbook operativo —cuándo correrlo, qué hacer si la API está caída, cómo leer un
`Infeasible`— está en [docs/runbook-fpl.md](docs/runbook-fpl.md).

## Arquitectura

**Entry points reales:** `mova_fpl/engine/runner.py::decide` es el único punto de decisión.
`cli/live.py` y `cli/backtest.py` son dos proveedores distintos del mismo `State`; eso es lo
que impide que producción y backtest diverjan.

```
data/     ingesta + almacén. Store.as_of(season, gw) es la ÚNICA lectura pública
rules/    reglas FPL puras y versionadas por temporada. Sin I/O, sin datos
models/   minutos (3 clases) · puntos por componente · DefCon · bonus · goles · CS
optimizer MILP con horizonte rodante (PuLP/CBC) + prefiltro + free hit aparte
agent/    contrato de intervención. NO decide: solo puede importar rules
engine/   decide(), proyección, políticas, planificador de chips, simulador, acta
trace/    corridas, decisiones y bitácora de intervenciones (SQLite)
cli/      7 comandos, ninguna lógica propia
```

**Dos fronteras que no son negociables**, ambas verificadas por prueba:

- **Chips:** el planificador *autoriza*, el optimizador *ejecuta* (ADR-008).
- **Agente:** mueve *entradas*, nunca la *salida* (ADR-009). No existe
  `force_captain`; hay un test que falla si alguien lo añade.

Flujo: `Store.as_of` → proyección de minutos → xP por componente → matriz de xP por
horizonte → MILP → `Decision` → acta en Markdown + fila en la traza.

## Reglas del repo

**Antes de dar algo por terminado:** `pytest -q` en verde. Cuatro pruebas son estructurales
y no se saltan:

| Prueba | Qué garantiza |
|---|---|
| `test_readonly_http.py` | Existe **un solo** `urlopen` en el paquete y su method es `GET`. Un bug no puede gastar transferencias reales (REQ-S-002) |
| `test_architecture_boundaries.py` | El grafo de importaciones respeta las capas y solo el simulador y el evaluador ven el oráculo |
| `test_store_as_of.py` | El contrato causal: ninguna lectura devuelve filas posteriores al `as_of` |
| `test_no_secrets.py` | No hay credenciales ni PII en el paquete |
| `test_agent_contract.py` | El agente no puede tocar plantilla, once ni capitán |

**Anti-leakage.** Todo dato entra por `Store.as_of(season, gw)`, que verifica el resultado
después de consultar, no antes. `assert_causal` está activa siempre, también en producción,
no solo bajo test. Si necesitas datos y no pasan por ahí, el diseño está mal, no el contrato.

**Solo lectura hacia afuera.** El motor nunca escribe en la API de FPL. El acta la introduce
una persona a mano (ADR-006). Añadir un POST rompe REQ-S-002 y la prueba lo bloquea.

Los endpoints `/api/entry/{id}/…` **sí** se leen (plantilla, banco, chips gastados): son
públicos y GET. Las superficies prohibidas siguen siendo `my-team` (autenticada),
`transfers` (POST) y `login`. La garantía no la da la lista negra sino que exista **un solo
`urlopen`** en el paquete y que declare `method="GET"`.

**Reentrenar.** `--holdout` es la temporada que NO entra al ajuste. Para operar 2026/27 el
holdout es `2025-26`. Cambiarlo sin pensarlo mete leakage.

**Determinismo.** El backtest con semilla 42 debe dar **2.220** puntos en 2025-26, y
**2.303** con `--chips`. Si da otra cosa, algo cambió: averiguar qué antes de operar.
(Fue 2.217 hasta que ADR-008 cerró un fallo en la linealización de las transferencias
libres, verificado por A/B.)

**Git.** Rama `feat/fpl-agent-clean`. Los `.joblib` y las `.db` están en `.gitignore`: son
regenerables y pesan. `outputs/*.md` también, salvo las actas bajo `outputs/fpl/`.

**Trampas conocidas.**
- `models/*.joblib` en la raíz son artefactos **legacy**. Los del motor viven en
  `models/minutes/` y `models/points/`.
- `data/mundial.db` (561 MB) es del Mundial, no de FPL. El motor no lo toca.
- El calendario se lee de datos ya ingeridos, así que incorpora reprogramaciones que en su
  momento podían no estar anunciadas (limitación L-01, declarada).

## Code intelligence

Repo indexado con CodeGraph (`.codegraph/`, auto-sync al guardar).

| Necesitas... | Comando |
|---|---|
| Entender un flujo / área | `codegraph explore "pregunta"` |
| Quién llama X / qué llama X | `codegraph callers\|callees <símbolo>` |
| Radio de impacto antes de refactorizar | `codegraph impact <símbolo>` |
| Qué tests correr tras un cambio | `git diff --name-only \| codegraph affected --stdin` |

⚠️ **Guardrails:**
- `impact`/`callers` con nombres genéricos mezcla homónimos → verificar con grep.
- No ve dispatch dinámico por string (`POLICIES["milp"]`, registro de modelos) → complementar
  con grep del nombre como string. En este repo aplica a `engine/policies.py::POLICIES` y a
  `models/registry.py`.
- El grafo refleja el working tree local, no otras ramas.

## Estado del código

- **Sano:** todo `mova_fpl/`. 600 pruebas, cero drift entre spec, código y comportamiento.
  Chips modelados y medidos (+83 pts); contrato de agente listo, sin agente todavía.
- **Degradado:** el componente de bonus subestima ~18% (H-WP005-02). La concordancia exacta
  con las acciones defensivas de Opta es 70,2%, no el 90% que pedía el criterio, con la causa
  aislada en los remates bloqueados (H-WP005-01). Ambas declaradas, ninguna silenciosa.
- **Pendiente de dato, no de código:** desde la GW2 hay que exportar `FPL_TEAM_ID` con el
  id del equipo (el de la URL `/entry/<ID>/`). El camino de lectura ya está construido y
  probado; sin el id, el motor arma desde cero y lo avisa.
- **Roto / no usar:** `src/mova_model/fpl_xp.py`, `src/mova_model/fpl_optimizer.py`,
  `src/mova_model/out_of_time_xp.py`, `scripts/live_agent_runner.py`,
  `scripts/train_fpl_xp_v*.py`, `scripts/sim_*.py`. Leakage estructural y números no
  reproducibles. Los docs `17`–`20` documentan ese código y llevan aviso.

## Desarrollo grande

- **Paquete canónico:** `docs/specs/fpl-decision-engine/` — brief, requisitos, arquitectura,
  7 ADRs, 7 workpacks, readiness, convergencia y evidencia.
- **Regla:** no activar el protocolo automáticamente. Solo cuando Julián invoque
  `$orbital-large-development` o pida la skill de desarrollo grande.
- **Fuente de verdad:** Git define la spec; Supabase `spec_v1` refleja hash, ejecución y
  evidencia. Los 7 SHA-256 coinciden entre ambos.
- **v1 está cerrada.** Lo que sigue —`entry_id` y GW2+, agente LLM de alineaciones probables,
  política de chips, cron— es una iniciativa nueva, no una extensión de esta.

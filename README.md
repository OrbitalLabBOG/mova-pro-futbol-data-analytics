# MOVA Fantasy Fútbol Data Analytics

Analítica de fútbol de la vertical **MOVA** (Orbital Lab): datos de eventos, modelos
probabilísticos y agentes de decisión.

El repositorio tiene **dos capítulos**. Uno está vivo y el otro cerrado.

| | Capítulo | Estado |
|---|---|---|
| **1** | **Motor de decisión FPL** — juega la Fantasy Premier League 2026/27 | 🟢 **Vivo.** v1 cerrada, opera la GW1 |
| 2 | Mundial 2026 y apuestas cuantitativas | ✅ Cerrado (jul-2026). Se conserva como registro |

---

# 1 · Motor de decisión FPL

Un sistema que, antes del cierre de cada jornada, lee el estado público de la liga, proyecta
puntos esperados jugador por jugador y emite un **acta de decisión**: qué quince fichar, qué
once alinear, a quién dar el brazalete, qué transferencias hacer y cuáles no valen el golpe.

El acta es un documento. **El motor de decisión no escribe en FPL**: su única primitiva de
red es un `GET`, verificado por pruebas. El stack autónomo incorpora un browser aislado que
lee el estado privado mediante un GET autenticado y entrega al motor únicamente una allowlist
sanitizada; cookies y sesión nunca cruzan esa frontera. El rollout sigue cerrado
(`shadow / A0`, kill switch activo y writes en cero).
La captura privada usa cadencia adaptativa según la distancia al deadline (6 h, 1 h,
15 min o 5 min) y sólo enciende el browser cuando el estado vence ese umbral.

## Qué tan bueno es

Backtest ciego de la temporada 2025-26 completa, con información estrictamente causal
—en cada jornada el motor solo ve lo que existía antes del deadline— y con los nombres de
jugadores y clubes anonimizados para que no pueda reconocer el año.

| Configuración | Puntos | vs. copiar a la multitud |
|---|---:|---:|
| Punto de partida del proyecto | 1.302 | −741 |
| \+ modelo de minutos | 1.298 | −745 |
| \+ optimizador MILP | 2.131 | +88 |
| **\+ modelo de puntos por componentes** | **2.217** | **+174** |
| *Baseline* `template` (los 15 más elegidos) | 2.043 | — |
| *Baseline* aleatorio | 533 | — |
| Techo con información perfecta | 5.871 | — |

Captura del techo: **37,8%**.

**Lo que esto no dice:** que vaya a ganar la temporada 2026/27. Dice que en 2025-26, sin
mirar el futuro, habría sacado 174 puntos más que copiar al rebaño. Una temporada es una
muestra de una.

## Cómo está hecho

```
Store.as_of(temporada, jornada)      ← única lectura de datos, verificada contra el futuro
        ↓
modelo de minutos {0, 1-59, 60+}     ← calibrado, ECE 0,0106
        ↓
xP por componente                    ← aparición, goles, asistencias, portería a cero,
        ↓                              goles encajados, DefCon, bonus, tarjetas, paradas
matriz de xP × horizonte             ← descuento 0,84^t, dobles ×2, blancos 0
        ↓
MILP (PuLP/CBC)                      ← plantilla, once, capitán, compras y ventas, golpes
        ↓
acta en Markdown + traza
```

Cinco decisiones que sostienen todo:

1. **Un solo contrato de lectura.** Todo pasa por `as_of()`, que comprueba el resultado
   después de consultar. El leakage deja de ser escribible; no es una convención que alguien
   deba recordar en la revisión.
2. **Una sola `decide()`.** El backtest y la operación en vivo son dos proveedores del mismo
   estado. No pueden divergir.
3. **Reglas puras y versionadas por temporada.** Las de 2026/27 no son las de 2025-26 —cambió
   el BPS y entró DefCon—. Validadas contra 29.757 actuaciones reales: **100% exacto**.
4. **xP descompuesto, no una regresión monolítica.** Cada componente con su distribución:
   Poisson para goles y encajados, binomial negativa para DefCon, Bernoulli para portería a
   cero. Descomponer no solo explica: destapó dos sesgos que el total ocultaba porque se
   compensaban entre sí.
5. **Fronteras verificadas por test.** El grafo de importaciones se comprueba, no se acuerda.

## Correr

```bash
python -m mova_fpl.data.ingest --all                      # almacén canónico, idempotente
python -m mova_fpl.cli.train_minutes --production --version 1.1.0
python -m mova_fpl.cli.train_points  --production --version 1.1.0

python -m mova_fpl.cli.collect_live --season 2026-27 --gw 1  # snapshot sellado + hashes

python -m mova_fpl.cli.live --season 2026-27 --gw 1 --horizon 3 --top-k 0   # ← el acta, ~6 s
```

El acta queda en `outputs/fpl/2026-27/gw01_decision.md`.

```bash
python -m mova_fpl.cli.backtest --season 2025-26 --policy milp --projector points --horizon 3
pytest -q                                                 # suite rápida completa
```

## Documentación

| Doc | Para qué |
|---|---|
| **[docs/runbook-fpl.md](docs/runbook-fpl.md)** | **Operar una jornada**, incluso si algo se rompió. Empezar aquí |
| **[docs/runbook-fpl-vps.md](docs/runbook-fpl-vps.md)** | **Operar/deplegar el control plane VPS**, logs, métricas, backups y hard stop |
| [docs/21-motor-fpl-arquitectura.md](docs/21-motor-fpl-arquitectura.md) | Cómo funciona por dentro: módulos, modelos, decisiones |
| [CLAUDE.md](CLAUDE.md) | Contexto técnico para trabajar en el repo |
| [docs/specs/fpl-decision-engine/](docs/specs/fpl-decision-engine/) | Paquete de diseño: brief, requisitos, 7 ADRs, 7 workpacks, evidencia |
| [docs/specs/fpl-decision-engine/04-convergence.md](docs/specs/fpl-decision-engine/04-convergence.md) | **Veredicto final**: qué quedó demostrado y qué no |
| [docs/specs/fpl-autonomous-operator/](docs/specs/fpl-autonomous-operator/) | Spec canónica de operación autónoma, observabilidad, VPS y rollout seguro |

## Lo que falta

- **El horizonte de producción.** Se opera con 3 por defecto razonado, no demostrado.
- **El agente de lenguaje** que lea alineaciones probables y ruedas de prensa. Es la
  información que hoy falta y que ningún almacén histórico puede dar.
- **Calibración multi-season de la política de chips.** Ya existe el planner y la legalidad
  2026/27; sus umbrales siguen siendo hipótesis hasta ampliar el backtest.
- **Rollout de escritura browser.** El runtime está aislado, pero seguirá en A0 hasta pasar
  compliance, login humano, verificación post-reload y shadow suficiente.

---

# 2 · Mundial 2026 y apuestas · cerrado

> **Ciclo completo** (2026-07-20). 🏆 España campeón (1-0 a Argentina). Datos completos:
> 104/104 partidos, 626K+ eventos. El modelo proyectó exactamente las dos semifinales reales
> y el pick de valor del *pick sheet* (España, leverage 1.31) fue el campeón.

Un pipeline que recolectó e interconectó siete fuentes públicas en una SQLite, un modelo
Elo → Dixon-Coles anclado a mercado, y una investigación de apuestas cuantitativas cuyo
veredicto fue negativo y está documentado como tal: **no se le gana al cierre de Pinnacle**
(backtest sobre 80.000 partidos).

| Doc | Contenido |
|-----|-----------|
| [00-estado.md](docs/00-estado.md) | Inventario, arquitectura y validación de la capa de datos |
| [01-panorama.md](docs/01-panorama.md) | Fase de grupos, upsets, tabla xG/suerte |
| [02-fuentes-datos.md](docs/02-fuentes-datos.md) | Disponibilidad de datos públicos, endpoints verificados |
| [03-supermodelos-referencia.md](docs/03-supermodelos-referencia.md) | Opta/Kalshi/Polymarket/casas y divergencias |
| [04-whoscored-collector.md](docs/04-whoscored-collector.md) · [05-…-data-dictionary.md](docs/05-whoscored-data-dictionary.md) | Event data: método, IDs, 39 eventos, 111 qualifiers |
| [06-fuentes-contexto-exploracion.md](docs/06-fuentes-contexto-exploracion.md) · [07-oddsapi.md](docs/07-oddsapi.md) | Elo/Kalshi/ESPN/StatsBomb y The Odds API |
| [08-marco-estadistico-y-modelo.md](docs/08-marco-estadistico-y-modelo.md) | ★ Marco estadístico y diseño del modelo |
| [09-modelo-mvp-resultados.md](docs/09-modelo-mvp-resultados.md) · [10-backtest-y-critica.md](docs/10-backtest-y-critica.md) | Resultados y veredicto honesto |
| [11-pronostico-y-operacion.md](docs/11-pronostico-y-operacion.md) | Pronóstico en vivo y cómo leer los picks |
| [12-estrategia-apuestas-investigacion.md](docs/12-estrategia-apuestas-investigacion.md) | ★ EV/devig/CLV/Kelly, referentes, plan accionable |
| [13-clv-backtest-resultados.md](docs/13-clv-backtest-resultados.md) | ★ **Prueba empírica de que no se le gana al cierre** |
| [14-polymarket-estrategia.md](docs/14-polymarket-estrategia.md) | Microestructura: veredicto (saturado para operador pequeño) |
| [15-postmortem-final.md](docs/15-postmortem-final.md) | ★ **Post-mortem: modelo vs. torneo real, lecciones** |
| [16-unificacion-fantasy-mova.md](docs/16-unificacion-fantasy-mova.md) | Unificación del repo como plataforma MOVA |
| [17](docs/17-fpl-engine-rules-and-strategy.md) · [18](docs/18-modelos-fpl-xp-e-inferencia.md) · [19](docs/19-motor-de-produccion-y-backtest-out-of-time.md) · [20](docs/20-aprendizaje-online-progresivo-y-sin-sesgo.md) | ⚠️ **Superados.** Documentan el intento previo de FPL, con leakage. Ver capítulo 1 |

```bash
python scripts/collect.py             # WhoScored: event data
python scripts/collect_context.py     # Elo + Kalshi + Polymarket + ESPN
python scripts/collect_odds.py        # The Odds API (credit-metered)
python scripts/validate.py            # integridad (PASS/WARN/FAIL)
python scripts/clv_backtest.py        # backtest CLV sobre 80K partidos
```

> ⚠️ `scripts/live_agent_runner.py`, `scripts/train_fpl_xp_v*.py` y `src/mova_model/fpl_*.py`
> son el **motor FPL anterior**, con leakage estructural y resultados no reproducibles.
> Están congelados como registro. El motor vigente es `mova_fpl/`.

---

## Estructura

```
mova-pro-futbol-data-analytics/
├── mova_fpl/               # ★ motor FPL v1 — lo único vivo
│   ├── data/               #   ingesta + Store.as_of (única lectura)
│   ├── rules/              #   reglas FPL puras, versionadas por temporada
│   ├── models/             #   minutos · puntos por componente · DefCon · bonus
│   ├── optimizer/          #   MILP con horizonte rodante (PuLP/CBC)
│   ├── engine/             #   decide(), proyección, políticas, simulador, acta
│   ├── trace/              #   persistencia de corridas y decisiones
│   ├── ops/                #   ledger, scheduler, observabilidad y backups del VPS
│   └── cli/                #   live · backtest · train_* · eval_* · rules_diff
├── deploy/                 # imágenes, systemd, bootstrap y restore drill
├── compose.yaml            # API local + worker one-shot + browser aislado
├── tests/                  # suite rápida + 2 pruebas `slow` de temporada completa
├── docs/                   # 00-20 + runbook + specs/fpl-decision-engine/
├── src/                    # ⚠️ legacy congelado (Mundial + FPL anterior)
├── scripts/                # ⚠️ legacy congelado
├── data/processed/         # fpl_canonical.db (254K filas, 10 temporadas) + trace.db
├── models/{minutes,points}/# artefactos del motor (gitignored, se regeneran)
└── outputs/fpl/            # actas de decisión por jornada
```

## Entorno

Python 3.13.5 vía conda (`/home/jzuluaga/miniconda3/bin/python3`).

```bash
pip install -r requirements.txt
```

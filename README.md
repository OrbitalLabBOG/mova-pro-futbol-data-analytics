# MOVA Mundial 2026 — Predictor de la Polla

Modelo de predicción de resultados para la **Copa Mundial FIFA 2026** (USA/México/Canadá, 48 equipos).
Objetivo práctico: maximizar el puntaje esperado en la polla. Objetivo técnico: pipeline reutilizable de analítica deportiva (vertical **MOVA**).

> **Estado: TORNEO TERMINADO — ciclo completo ✅** (2026-07-20). 🏆 **España campeón** (1-0 a Argentina). Datos completos: 104/104 partidos, 626K+ eventos. El modelo proyectó exactamente las dos semifinales reales (Francia-España, Argentina-Inglaterra) y el **pick de valor del pick sheet (España, leverage 1.31) fue el campeón**. Balance final y lecciones → **[docs/15-postmortem-final.md](docs/15-postmortem-final.md)**.

## Tesis del proyecto

El formato de 48 equipos ha **subido la varianza** (más empates, más debutantes, calor y viajes castigando a favoritos). En polla con alta varianza conviene mezclar *chalk* (favoritos sólidos) con apuestas de valor controlado, no clavar todos los favoritos.

## Enfoque de modelamiento (planeado)

Stack inspirado en lo que la evidencia dice que funciona:

1. **Elo / Power Ratings** — el driver dominante (~80% del poder predictivo según comparativas de 10+ modelos).
2. **Dixon-Coles** — modelo de goles (Poisson bivariado con corrección para marcadores bajos) → probabilidades por partido.
3. **Ajuste por xG / suerte** — corregir sobre/sub-rendimiento de la fase de grupos (regresión a la media).
4. **Ajustes de contexto** — ventaja local (anfitriones), calor, viajes entre sedes, descanso.
5. **Monte Carlo del bracket** — simular la Ronda de 32 → final N veces para win-probabilities y bracket óptimo.
6. **Calibración vs. mercado** — contrastar con Kalshi/Polymarket/Opta para detectar *value* y errores del modelo.

## Estructura

```
mova-mundial-2026/
├── docs/                   # 00-estado (cierre fase 1) + 01-07 investigación/fuentes
├── src/mova_data/          # paquete del pipeline
│   ├── config.py db.py teams.py matches_map.py
│   ├── collectors/         # 1 por fuente (base.py = interfaz pluggable)
│   └── loaders/            # JSON cache → SQLite
├── scripts/                # collect*, build_aliases, build_match_map, validate, explore
├── data/
│   ├── raw/                # cache crudo por fuente (gitignored)
│   └── mundial.db          # SQLite interconectada (gitignored, se regenera)
├── notebooks/ models/ outputs/   # fase 2
└── .env.local              # ODDS_API_KEY (gitignored; ver .env.local.example)
```

Arquitectura, inventario de datos y plan de Fase 2 → **[docs/00-estado.md](docs/00-estado.md)**.

## Documentación

| Doc | Contenido |
|-----|-----------|
| [docs/00-estado.md](docs/00-estado.md) | **Cierre Fase 1: inventario, arquitectura, validación, plan Fase 2** |
| [docs/01-panorama.md](docs/01-panorama.md) | Resultados fase grupos, upsets, tabla xG/suerte, modelos, mercados |
| [docs/02-fuentes-datos.md](docs/02-fuentes-datos.md) | **Disponibilidad de datos públicos/gratis, endpoints verificados, stack recomendado** |
| [docs/03-supermodelos-referencia.md](docs/03-supermodelos-referencia.md) | Probabilidades actuales de Opta/Kalshi/Polymarket/casas + divergencias = value |
| [docs/04-whoscored-collector.md](docs/04-whoscored-collector.md) | **Collector de event data (mina de oro): método, IDs, endpoints, arquitectura** |
| [docs/05-whoscored-data-dictionary.md](docs/05-whoscored-data-dictionary.md) | **Diccionario de datos WhoScored: campos, tipos, 39 eventos, 111 qualifiers, coords** |
| [docs/06-fuentes-contexto-exploracion.md](docs/06-fuentes-contexto-exploracion.md) | **Exploración de Elo/Kalshi/ESPN/StatsBomb: campos reales + diseño de tablas** |
| [docs/07-oddsapi.md](docs/07-oddsapi.md) | The Odds API: modelo de créditos, endpoints, tabla granular |
| [docs/08-marco-estadistico-y-modelo.md](docs/08-marco-estadistico-y-modelo.md) | **★ Marco estadístico + diseño del modelo (Fase 2)** |
| [docs/09-modelo-mvp-resultados.md](docs/09-modelo-mvp-resultados.md) | Resultados del MVP del modelo (E0-E4) |
| [docs/10-backtest-y-critica.md](docs/10-backtest-y-critica.md) | **★ Backtest, experimentos y veredicto honesto (qué tan bueno es)** |
| [docs/11-pronostico-y-operacion.md](docs/11-pronostico-y-operacion.md) | **★ Pronóstico en vivo, salidas, cómo regenerar y leer los picks** |
| [docs/12-estrategia-apuestas-investigacion.md](docs/12-estrategia-apuestas-investigacion.md) | **★ Apuestas cuantitativas: matemática (EV/devig/CLV/Kelly), referentes, Polymarket, fuentes de datos, veredicto +EV y plan accionable** |
| [docs/13-clv-backtest-resultados.md](docs/13-clv-backtest-resultados.md) | **★ Backtest de CLV sobre 80K partidos: prueba empírica de que NO se le gana al cierre de Pinnacle (mercados eficientes)** |
| [docs/14-polymarket-estrategia.md](docs/14-polymarket-estrategia.md) | **★ Polymarket por microestructura (MM/arb/resolution-edge): medición en vivo + veredicto (saturado para operador pequeño)** |
| [docs/15-postmortem-final.md](docs/15-postmortem-final.md) | **★ Post-mortem final: qué tan bueno fue el modelo vs el torneo real, por qué se desfasó el pick de campeón, lecciones** |

## Cómo correr el pipeline

```bash
# ── Datos (collectors, idempotentes) ──
python scripts/collect.py            # WhoScored: event data (discover→fetch→load)
python scripts/collect_context.py    # Elo + Kalshi + Polymarket + ESPN (diario)
python scripts/collect_odds.py       # The Odds API (credit-metered, ~4/día)
python scripts/collect_statsbomb.py  # StatsBomb WC2022/2018 (entrenamiento)
python scripts/collect_elo_history.py # histórico martj42 + Elo propio (una vez)
python scripts/build_aliases.py      # identidad canónica de equipos
python scripts/build_match_map.py    # enlazar partidos entre fuentes
python scripts/validate.py           # validar integridad (PASS/WARN/FAIL)

# ── Modelo (Fase 2) ──
python scripts/train_xg.py           # entrena xG nativo WhoScored (una vez)
python scripts/fit_match_model.py    # calibra Elo→Dixon-Coles (una vez)
python scripts/run_model.py --seed 42  # ★ pipeline: features→predict→simulate→insight
python scripts/backtest.py           # RPS leakage-free WC2018/22
python scripts/scout.py "Colombia" "Ghana"  # scouting táctico de un cruce
python scripts/bracket.py            # bracket completo lleno (16vos→campeón)

# ── Apuestas / CLV (Fase betting) ──
python scripts/collect_club_odds.py  # mirror football-data → data/betting.db (80K con cierre Pinnacle)
python scripts/clv_backtest.py       # ★ backtest CLV: ¿le ganamos al cierre? (4 tests, ~34s)
python scripts/poly_microstructure.py # ★ microestructura PM+Kalshi en vivo (sandbox OFF; curl_cffi)
```

Todo idempotente y source-agnostic (`source` en cada tabla). DB: `data/mundial.db`.
Salidas del modelo: tabla `tournament_sim` (P avance/campeón) + `outputs/insight_latest.md`.

## Stack de datos (gratis + permanente) — resumen

> ⚠️ **Clave:** el 20-ene-2026 FBref perdió la licencia Opta y Stats Perform quedó como distribuidor **exclusivo** de datos WC2026 → **no hay event data crudo gratis del Mundial 2026**. Estrategia: entrenar con histórico gratis + alimentar WC2026 con xG agregado. Detalle en [docs/02-fuentes-datos.md](docs/02-fuentes-datos.md).

- **Resultados/live**: ESPN hidden API + FIFA v3 (sin key, en vivo) + football-data.org (fallback).
- **Event data (train)**: StatsBomb Open Data (`statsbombpy`, hasta WC2022).
- **Event data (WC2026)**: Kaggle `mominullptr` (CC0, xG agregado diario).
- **Ratings**: eloratings.net/World.tsv (sin key) — el gap de Elo es el predictor #1.
- **Mercados**: Kalshi `KXMENWORLDCUP` (sin auth) + The Odds API (500/mes) + Polymarket Gamma.
- **Open-source base**: github.com/Hicruben/world-cup-2026-prediction-model (Elo + Dixon-Coles + Monte Carlo).

## Entorno

Python vía conda: `/home/jzuluaga/miniconda3/bin/python3` (3.13). Libs previstas: pandas, numpy, scipy, statsmodels, requests/httpx, matplotlib.

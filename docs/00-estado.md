# Estado del proyecto — cierre Fase 1 (Capa de Datos)

> **Fase 1: COMPLETADA** ✅ (2026-06-28). Capa de datos multi-fuente, interconectada y validada. Lista para Fase 2 (features + modelo).

## Qué se construyó

Un **pipeline de datos** del Mundial FIFA 2026 que recolecta, normaliza e interconecta 7 fuentes públicas/gratuitas en una SQLite (`data/mundial.db`), con identidad canónica de equipos y enlace de partidos entre fuentes.

## Inventario de datos (validado)

| Dato | Cantidad |
|---|---|
| Eventos WhoScored (Mundial 2026, con coordenadas) | **112,059** |
| Eventos StatsBomb (WC2022+2018, con xG oficial — entrenar) | **462,462** |
| Partidos (fixtures) | 88 (73 jugados con eventos) |
| Alineaciones · jugadores · equipos | 3,743 · 1,247 · 48 |
| Ratings Elo | 48/48 selecciones |
| Cuotas de casas (25 bookmakers) | 1,931 |
| Prob. de mercado (Kalshi/Polymarket/OddsAPI) | series temporales |
| Fixtures ESPN + moneyline | 104 |
| **Total eventos (con coordenadas)** | **574,521** |

Disco: DB 61 MB + cache crudo ~1.1 GB (gitignored, se regenera).

## Fuentes integradas

| Fuente | Datos | Acceso | Doc |
|---|---|---|---|
| **WhoScored** | Event data (mina de oro) | CloudScraper, sin key | [04](04-whoscored-collector.md), [05](05-whoscored-data-dictionary.md) |
| **StatsBomb** | Event data histórico + xG | statsbombpy, sin auth | [06](06-fuentes-contexto-exploracion.md) |
| **Elo** | Rating selecciones | TSV, sin key | [06](06-fuentes-contexto-exploracion.md) |
| **Kalshi** | Prob. mercado (USA) | API, sin auth | [06](06-fuentes-contexto-exploracion.md) |
| **Polymarket** | Prob. mercado (cripto) | Gamma API, sin auth | [06](06-fuentes-contexto-exploracion.md) |
| **ESPN** | Fixtures + odds DK | API, sin key | [06](06-fuentes-contexto-exploracion.md) |
| **The Odds API** | Odds multi-casa | API key (free 500/mes) | [07](07-oddsapi.md) |

## Arquitectura

```
src/mova_data/
├── config.py            # IDs torneo, rutas, lee .env.local (ODDS_API_KEY)
├── db.py                # esquema SQLite (source-agnostic) + vistas
├── teams.py             # identidad canónica + resolver de aliases
├── matches_map.py       # enlace de partidos entre fuentes
├── collectors/          # 1 por fuente (base.py = interfaz pluggable)
│   ├── whoscored.py kalshi.py polymarket.py espn.py oddsapi.py
│   ├── elo.py statsbomb.py
└── loaders/whoscored.py # JSON cache → SQLite
scripts/
├── collect.py           # WhoScored (discover→fetch→load)
├── collect_context.py   # Elo+Kalshi+Polymarket+ESPN (diario)
├── collect_odds.py      # OddsAPI (credit-metered)
├── collect_statsbomb.py # entrenamiento xG
├── build_aliases.py     # poblar team_aliases
├── build_match_map.py   # enlace de partidos
├── explore_sources.py   # explorar muestras crudas
└── validate.py          # integridad (PASS/WARN/FAIL)
```

**Principios:** descarga ≠ parseo (cache crudo en disco) · idempotente (re-correr baja solo lo nuevo) · source-agnostic (columna `source` en cada tabla de hechos) · explore→document→tablas.

## Interconexión

- **Equipo:** `team_aliases` → vista `v_team_board` (Elo + 3 mercados por equipo).
- **Partido:** `match_map` → vista `v_match` (WhoScored ↔ ESPN ↔ OddsAPI).
- **StatsBomb:** separado a propósito (cache de entrenamiento).

## Validación (scripts/validate.py — TODO OK, 0 fallos)

- Integridad referencial: 0 huérfanos.
- **Goles en eventos = marcadores: 215 = 215** (0 partidos difieren).
- Rangos OK (coords [0,100], probs [0,1], cuotas ≥1).
- match_map: ids únicos y existentes, 88/88 mapeados.
- Hallazgo benigno: WhoScored trae 5 ids de evento duplicados → `UNIQUE` los limpió (DB más limpia que la fuente).

## Cómo mantener al día

```bash
python scripts/collect.py            # eventos nuevos (R16, cuartos…)
python scripts/collect_context.py    # Elo + mercados (diario)
python scripts/collect_odds.py       # OddsAPI (~4 créditos/día)
python scripts/build_match_map.py    # re-enlazar partidos nuevos
python scripts/validate.py           # verificar integridad
```
> Las odds solo existen **pre-partido**; los eventos solo **post-partido**. Correr a diario completa la cadena por partido vía `match_map`.

---

## Fase 2 — Features + Modelo (pendiente)

1. **xG propio** — entrenar con StatsBomb (`shot_statsbomb_xg`) y aplicar a tiros de WhoScored (que no traen xG).
2. **Agregados por equipo/partido** — xG for/against, tiros, posesión, PPDA, big chances → tabla plana de features.
3. **Features de contexto** — Elo gap, consenso de mercado, divergencia entre mercados (señal de value).
4. **Modelo** — Elo + Dixon-Coles + Monte Carlo del bracket → probabilidades de avance y de campeón.
5. **Backtesting / calibración** vs Opta y mercados (Brier score).
6. (Opcional) Cron de actualización automática.

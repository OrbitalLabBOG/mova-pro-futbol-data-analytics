# Estado del proyecto

> **Fase 1 (Datos) ✅ + Fase 2 (Modelo) ✅** (2026-06-28). Capa de datos multi-fuente validada + modelo Elo→Dixon-Coles anclado a mercado, backtesteado, con capas de insight y scouting. Siguiente: Fase 3 (estrategia de polla).

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

## Fase 2 — Modelo (COMPLETADA, MVP + refinamiento) ✅

Paquete `src/mova_model/` (idempotente, re-ejecutable con datos frescos):
- **Datos históricos:** `intl_results` (49.477 partidos martj42) + Elo propio (`elo_computed`).
- **xG propio:** entrenado **nativo WhoScored** con BigChance (Brier 0.080, xG agregado insesgado).
- **Motor:** Elo→Dixon-Coles (ρ=−0.045) → P(1X2). Core = **Elo puro** (el backtest probó que xG/features no mejoran el ranking).
- **Anclaje a mercado:** log-pool (w=0.65) → calibrado ≈ Opta (Argentina 22.4 / France 21.3 / Spain 13.4).
- **Simulación:** bracket WC2026 fijo, convolución exacta (DP) = Monte Carlo → `tournament_sim` (P avance/campeón).
- **Capa insight:** valor vs mercado, suerte/regresión (goles−xG), camino de bracket → `outputs/insight_latest.md`.
- **Capa scouting:** táctica por matchup desde eventos WC2026 (`scripts/scout.py`).

### Veredicto honesto (docs/10)
- **Backtest leakage-free WC2018/22:** RPS 0.216 ≈ casas (~0.20) → el modelo está **al nivel del mercado, no por encima**. Batir al mercado en selección es casi imposible.
- **Experimentos (aprender pesos ML, forma, xG, táctica):** todas las mejoras (0.001-0.006) son **< ruido** (SE±0.008-0.014) → estadísticamente nulas. Elo+mercado es el techo predictivo.
- **El edge para ganar la polla NO es el modelo** (es ≈ mercado) → está en la **capa de estrategia** (valor vs público, ownership, camino) + scouting como desempate.

## Fase 3 — Estrategia de polla (pendiente)

1. **Ownership/valor vs el público** (sesgo nacional: Colombia/Brasil/Argentina sobre-elegidos).
2. **Optimización de picks** que maximice P(quedar 1º) simulando contra el campo.
3. Scouting por-matchup como desempate.
4. (Opcional con evidencia) valor de plantilla Transfermarkt, Elo-trayectoria; cron de actualización.

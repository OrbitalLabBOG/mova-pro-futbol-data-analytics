# Fuentes de contexto — exploración de datos reales

> Exploradas el **2026-06-28** con `scripts/explore_sources.py`. Muestras crudas en `data/raw/_explore/`. **Documentamos campos y tipos ANTES de diseñar tablas** (mismo método que con WhoScored). El diseño de tablas va en §5.

---

## 1. Elo — eloratings.net/World.tsv

- **Acceso:** GET directo del TSV. Sin auth. CloudScraper/requests funciona (200 verificado).
- **Forma:** **244 filas × 31 columnas**, TSV **sin cabecera**, números con signo unicode (`−` U+2212, no `-` ASCII).
- **Columnas que usamos** (resto son deltas/contadores históricos):

| idx | contenido | tipo | ejemplo |
|----|-----------|------|---------|
| 0 | rank actual | int | 1 |
| 1 | rank (referencia) | int | 1 |
| 2 | **código ISO eloratings** | str | `AR`, `ES`, `EN`, `SCO` |
| 3 | **rating Elo** | int | 2148 |
| 4-30 | deltas/medias (1y, picos, partidos) | str±  | `+35`, `−7` |

- **Muestra real:** Argentina (AR) 2148 · España (ES) 2144 · Francia (FR) 2123 · Inglaterra (EN) 2038.
- **Cobertura:** todas las selecciones FIFA, se actualiza tras cada partido. ⚠️ Código propio (`EN`=England, `SCO`=Scotland) ≠ nombre WhoScored → requiere **mapa ISO→equipo** (48 del Mundial).
- **Tipo de dato a guardar:** snapshot diario (rank, rating por iso).

## 2. Kalshi — mercados del Mundial (probabilidad real, dinero)

- **Acceso:** `GET api.elections.kalshi.com/trade-api/v2/markets?series_ticker={S}&status=open`. **Sin auth para lectura.** JSON.
- **Serie ganador:** `KXMENWORLDCUP` → **32 mercados** (uno por selección viva), **32/32 con precio**.
- ⚠️ **Los precios viven en campos con sufijo `_dollars` y son STRING** (no los `yes_bid`/`last_price` sin sufijo, que salen `null`).

| campo | tipo | significado |
|---|---|---|
| `ticker` | str | `KXMENWORLDCUP-26-FRA` |
| `yes_sub_title` | str | nombre del equipo (`France`) |
| `last_price_dollars` | str→float | **prob. implícita 0-1** (`"0.2490"`) |
| `yes_bid_dollars` / `yes_ask_dollars` | str→float | bid/ask |
| `previous_price_dollars` | str→float | precio previo |
| `volume_fp` / `volume_24h_fp` / `open_interest_fp` | float | liquidez |
| `status`, `result`, `close_time` | str | estado del mercado |

- **Muestra real (28-jun):** France 0.249 · Argentina 0.213 · Spain 0.104 · England 0.099 · Portugal 0.066 · Netherlands 0.062 · Brazil 0.061. (Coincide con [03-supermodelos](03-supermodelos-referencia.md) ✓.)
- **Otras series WC disponibles (40+):** `KXWCSPREAD`, `KXWCCORNERS`, `KXWCSHOT`, `KXWCTEAMTOTAL`, `KXWCGOALLEADER`, `KXWC1HTOTAL`… (mercados por partido/prop — útiles más adelante).
- **Tipo de dato a guardar:** snapshot con timestamp (para serie temporal de probabilidades).

## 3. ESPN — fixtures + odds de casas (sin key)

- **Acceso:** `GET site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=YYYYMMDD-YYYYMMDD`. Sin auth. JSON. (16 eventos para R32.)
- **Estructura:** `events[]` → `competitions[0]` → `competitors[]` (home/away) + `odds[]`.

| nivel | campos clave | tipo |
|---|---|---|
| event | `id, date, name, shortName, status, venue` | mixto |
| competition | `attendance, competitors, odds, details, status` | mixto |
| competitor | `homeAway, winner, score, form, team{displayName...}, statistics[]` | mixto |
| status | `type.name` (`STATUS_SCHEDULED`/`STATUS_SECOND_HALF`/`STATUS_FULL_TIME`) | str |
| odds[0] | provider=**DraftKings**; `moneyline{home/away/draw.{open/close/current}.odds}`, `pointSpread`, `total`, `overUnder` | str (american, ej. `"+8000"`, puede ser `"OFF"`) |

- **Valor agregado vs WhoScored:** odds de casa por partido (open/close/current), `form` reciente, `statistics` por equipo, y **fixtures futuros** (antes de jugarse). Scores en vivo.
- ⚠️ FIFA world ranking: el endpoint `/standings` devolvió **vacío** → no hay ranking FIFA por aquí (descartar; usar Elo como rating dinámico).
- **Tipo de dato a guardar:** fixtures con scores + moneyline (american odds → convertir a prob).

## 4. StatsBomb Open Data — event data histórico para ENTRENAR

- **Acceso:** `statsbombpy` (instalado). Lee de GitHub, sin auth. Open Data User Agreement (no comercial + atribución).
- **`sb.competitions()`** → columnas: `competition_id, season_id, country_name, competition_name, competition_gender, season_name, match_available, match_available_360`.
- **Mundiales de selección disponibles (para entrenar xG / modelo de selecciones):**

| competition_id | season_id | torneo |
|---|---|---|
| 43 | 106 | **FIFA World Cup 2022** (64 partidos) |
| 43 | 3 | FIFA World Cup 2018 |
| 43 | 55/54/51/272/270/269 | WC 1990/1986/1974/1970/1962/1958 |
| 72 | 107 | Women's World Cup 2023 |

> ⚠️ **No incluye WC2026** (StatsBomb open llega hasta 2022). Sirve para **entrenar/calibrar**, no para el torneo en curso.

- **Eventos:** `sb.events(match_id)` → **3.388 filas × 91 columnas** por partido. Schema MUY distinto a WhoScored: ubicaciones como listas `[x,y]` (`location`, `carry_end_location`, `goalkeeper_end_location`), columnas por tipo (`pass_*`, `shot_*`, `dribble_*`, `duel_*`), **incluye `shot_statsbomb_xg` (xG oficial)** y freeze-frames 360 en algunas comps.
- Tipos de evento (muestra): Pass 955, Ball Receipt* 868, Carry 782, Pressure 289, Ball Recovery 93, Duel, Clearance, Dribble.
- **Clave:** trae **xG etiquetado** → es nuestro **set de entrenamiento para el modelo de xG propio** que aplicaremos a los tiros de WhoScored (que no traen xG).

---

## 5. Decisiones de diseño de tablas (informadas por lo explorado)

| Fuente | Tabla | Por qué así |
|---|---|---|
| Elo | `elo_ratings(source, snapshot_date, iso, team, rank, rating)` | snapshot diario; `team` mapeado vía dict ISO→WC; PK (source, date, iso) |
| Kalshi | `market_odds(source, captured_at, market_type, entity, prob, yes_bid, yes_ask, last_price, ticker)` | serie temporal de prob; genérica para sumar oddsapi/polymarket/espn después; precios casteados string→float |
| ESPN | `espn_fixtures(espn_id, date_utc, status, home/away_team, home/away_score, ml_home/draw/away, venue, updated_at)` | fixtures + moneyline; american odds guardados como int |
| StatsBomb | **cache en disco** `data/raw/statsbomb/` + (opcional) tablas propias luego | schema de 91 columnas muy distinto; no forzar al modelo unificado todavía; es para entrenar, no para el torneo |

**Principios reafirmados:** toda tabla de hechos lleva `source`; mercados van a una sola tabla genérica para mezclar proveedores; StatsBomb se cachea crudo y su normalización se decide cuando ataquemos el modelo de xG (no antes).

> Tablas y collectors se implementan en el siguiente paso, ya con estos campos reales confirmados.

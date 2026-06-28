# Fuentes de datos — disponibilidad pública y gratuita

> Investigado y verificado en vivo el **2026-06-28** (Ronda de 32). Endpoints marcados **[✓]** se probaron con curl/fetch hoy; **[doc]** = documentado pero no probado desde este entorno (bloqueo de egress WSL/Cloudflare).

## 🔴 El hallazgo que define la estrategia

**El 20-ene-2026, FBref perdió su licencia Opta y Stats Perform (Opta) quedó como distribuidor EXCLUSIVO de los datos del Mundial 2026.**

Consecuencias:
- **NO existe ninguna fuente gratis con event data crudo (shot/pass events con coordenadas, freeze-frames) del Mundial 2026.** Eso vive en Opta/Stats Perform (de pago) o StatsBomb (de pago para data nueva).
- FBref ya **no publica xG ni stats avanzadas** (solo resultados/alineaciones básicas).

**Estrategia realista en consecuencia:**
1. **Entrenar** el modelo con event data histórico gratis (StatsBomb Open Data, hasta WC2022 + Euro2024/CopaAmérica2024).
2. **Alimentar el WC2026 en curso** con xG y stats **agregadas por partido** (no a nivel de evento) desde fuentes scrapeables / Kaggle.
3. Donde necesitemos eventos crudos de WC2026 → habría que licenciar (no gratis).

---

## 1. Resultados, fixtures, standings (en vivo)

| Fuente | Cobertura WC2026 | Auth | Free tier | Frescura | Veredicto |
|---|---|---|---|---|---|
| **ESPN hidden API** [✓] | Live + standings + stats por partido | Ninguna | Sin cap documentado | **En vivo** | ⭐ Motor live primario |
| **FIFA api.fifa.com/v3** [✓] | Oficial (Comp 17 / Season 285023) | Ninguna | Sin límite documentado | **En vivo/oficial** | ⭐ Fuente de verdad |
| **football-data.org** [✓] | WC + 12 comps + histórico | API key gratis (obligatoria) | 10 req/min; **scores con delay** | Diferido | Backfill/histórico estable |
| **openfootball/worldcup.json** [✓] | WC2026 + Mundiales pasados | Ninguna | Límites de GitHub | Batch (~diario) | Fallback/seed, dominio público |
| API-Football / Highlightly | Live completo | API key | **100 req/día** (muy bajo) | Live | Solo prototipo / si se paga |
| Sportmonks (free) | ❌ Sin WC (solo DK/SCO) | API key | — | — | ✗ No usable gratis |

### Endpoints listos para cablear
```
# ESPN (live, sin key) — fifa.world = WC2026
https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=20260628
https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/standings
https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={id}   # play-by-play, stats, lineups

# FIFA (oficial, sin key) — IdCompetition=17, IdSeason=285023
https://api.fifa.com/api/v3/calendar/matches?idCompetition=17&idSeason=285023&count=200&language=en
https://api.fifa.com/api/v3/live/football/now?language=en

# football-data.org (requiere header X-Auth-Token gratis)
https://api.football-data.org/v4/competitions/WC/matches

# openfootball (fallback, sin key, dominio público)
https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json
```
> ⚠️ ESPN y FIFA son APIs **no oficiales** (reverse-engineered). Pueden cambiar sin aviso → **cachear agresivo** (5–15s live, más para fixtures) y mantener football-data.org + openfootball como fallback.

---

## 2. Event data y stats avanzadas (xG, tiros, pases)

| Fuente | Tipo | Cobertura WC2026 | Acceso | Licencia | Librería Python |
|---|---|---|---|---|---|
| **StatsBomb Open Data** | Event data completo (xG, shots, pases, 360) | **NO** (hasta WC2022 + Euro24/CopaAmérica24) | Repo GitHub JSON | No comercial + atribución | `statsbombpy`, `socceraction`, `mplsoccer` |
| **Kaggle WC2026** (mominullptr) | Agregado/partido + event log min-a-min + **xG/partido** | ✅ **Sí, diario** | Descarga Kaggle/GitHub | **CC0** (comercial OK) | `kagglehub` |
| **FBref** (post-Opta) | Solo básico (sin xG ya) | Resultados sí, xG no | Scraping | ToS restrictivo | `soccerdata`, `ScraperFC` |
| **Understat** | xG a nivel de tiro (x,y) | ❌ Solo Big-5 + RPL | Scraping JSON | Tolerado | `understatapi`, `soccerdata` |
| **Opta/TheAnalyst** | xG, Power Ratings, supercomputer | ✅ pero solo en artículos | Web (no exportable) | Propietario (exclusivo WC2026) | — |
| **Sofascore** | xG + stats/partido | ✅ | API no oficial / scrape | ToS prohíbe scrape | `soccerdata` (clase Sofascore) |
| Wyscout (Hudl) | Event data pro + video | ✅ pero de pago | Plataforma | Propietario (€299+/año) | — |

### Cómo conectarse (lo clave)
```python
# Entrenamiento: StatsBomb Open Data (event data histórico gratis)
from statsbombpy import sb
comps = sb.competitions()                                  # busca "FIFA World Cup"
matches = sb.matches(competition_id=43, season_id=106)     # WC2022
events  = sb.events(match_id=3869685)                      # eventos completos + xG
# socceraction → convertir a SPADL/VAEP para modelar

# WC2026 en curso: Kaggle CC0 (xG agregado + event log, actualizado a diario)
import kagglehub
path = kagglehub.dataset_download("mominullptr/fifa-world-cup-2026-dataset")
```
> El dataset Kaggle declara fuentes FIFA.com + Sofascore + FBref. Es **comunitario** → validar calidad del xG. Pero es la **única fuente WC2026 gratis con licencia limpia (CC0)** y a nivel de evento temporal.

---

## 3. Ratings de selecciones (feature de fuerza)

| Fuente | Acceso | Auth | Frescura | WC2026 |
|---|---|---|---|---|
| **eloratings.net** [✓] | TSV directo | Ninguna | Tras cada partido FIFA | ✅ selecciones |
| FIFA/Coca-Cola Ranking | HTML scrape (no API) | — | ~mensual | ✅ seeding |
| ClubElo [✓] | `api.clubelo.com` CSV | Ninguna (requiere User-Agent) | Diario | ❌ **solo clubes** |
| Kaggle "WC2026 Historical Elo" | Descarga CSV | Token Kaggle | Snapshot | ✅ pre-torneo |

```
# Elo de selecciones (sin key, TSV) — VERIFICADO: fila 1 = AR 2148, fila 2 = ES 2144
https://www.eloratings.net/World.tsv
https://www.eloratings.net/2026.tsv
https://www.eloratings.net/{ISO2}.tsv     # historial de una selección
```
> TSV **sin cabecera**: rank, rank_prev, ISO, rating, deltas. Mapear columnas con `/about`. **El gap de Elo entre rivales es el predictor #1** (≈2 órdenes de magnitud sobre la siguiente variable).

---

## 4. Odds y mercados de predicción (target + feature + value)

| Fuente | Acceso | Auth | Free tier | WC2026 |
|---|---|---|---|---|
| **Kalshi** [✓] | `api.elections.kalshi.com/trade-api/v2` | **Ninguna para lectura** | Sin límite documentado | ✅ `KXMENWORLDCUP` + 40 series |
| **The Odds API** [✓] | `api.the-odds-api.com/v4` | `apiKey` query | **500 créditos/mes** | ✅ `soccer_fifa_world_cup(_winner)` |
| **Polymarket** [doc] | `gamma-api.polymarket.com` + `clob.polymarket.com` | Ninguna para lectura | Sin límite documentado | ✅ (validar slug) |
| football-data.co.uk | CSV directo | Ninguna | Gratis | ❌ ligas (odds históricas) |
| Betfair Exchange | API real | App Key + cuenta | Sin tier de datos limpio | ✅ pero alta fricción |
| Pinnacle | vía The Odds API | — | — | Indirecto (línea "sharp") |

```
# Kalshi — ganador del Mundial (sin auth) — VERIFICADO: 48 submercados por país
https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXMENWORLDCUP&status=open
# otras series: KXWCGROUPWINNER, KXWCFINALMATCHUP, KXWCCONTINENT...
# precios en yes_bid/yes_ask/last_price (centavos = prob. implícita 0-100)

# The Odds API (key gratis, 1 crédito por request dirigido)
https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup_winner/odds?regions=eu&markets=outrights&apiKey=KEY

# Polymarket Gamma (sin auth) — validar slug exacto en vivo
https://gamma-api.polymarket.com/events?slug=world-cup-2026-winner
```
> Con 500 créditos/mes de The Odds API: 1 request dirigido cada ~90 min cabe holgado. **Kalshi es la opción de menor fricción** (sin key, tiempo real, US-regulado).

---

## 5. Stack recomendado (gratis + permanente)

```
RESULTADOS/LIVE   → ESPN hidden API (primario) + FIFA v3 (canónico) + football-data.org (fallback)
EVENT DATA TRAIN  → StatsBomb Open Data (statsbombpy + socceraction)
EVENT DATA WC2026 → Kaggle mominullptr (CC0, diario) — xG agregado + event log
RATINGS           → eloratings.net/World.tsv (cron, sin key)
MERCADOS          → Kalshi (KXMENWORLDCUP, sin auth) + The Odds API (500/mes) + Polymarket Gamma
ODDS HISTÓRICAS   → football-data.co.uk (calibración odds→resultado)
```

Solo The Odds API requiere registrar un email para key gratis. Todo lo demás es sin credenciales o con token gratuito.

## 6. Notas de licencia (para uso comercial MOVA)
- **CC0 (Kaggle mominullptr):** comercial OK. ✅
- **StatsBomb Open Data:** no comercial + atribución/logo. ⚠️ Producto comercial → licenciar.
- **FBref/Understat/Sofascore (scraping):** zona gris ToS; OK investigación, riesgoso a escala comercial.
- **Opta/TheAnalyst, Wyscout:** propietario, requieren contrato.
- **ESPN/FIFA APIs no oficiales:** zona gris; cachear y no abusar.

## Fuentes
- ESPN API (community): https://github.com/pseudo-r/Public-ESPN-API
- football-data.org: https://www.football-data.org/pricing
- openfootball: https://github.com/openfootball/worldcup.json
- StatsBomb Open Data: https://github.com/statsbomb/open-data · `statsbombpy`: https://github.com/statsbomb/statsbombpy
- soccerdata: https://github.com/probberechts/soccerdata
- Kaggle WC2026: https://www.kaggle.com/datasets/mominullptr/fifa-world-cup-2026-dataset
- FBref pierde Opta: https://www.sports-reference.com/blog/2026/01/fbref-stathead-data-update/
- eloratings.net: https://www.eloratings.net · ClubElo: http://api.clubelo.com
- The Odds API: https://the-odds-api.com · Kalshi: https://trading-api.readme.io · Polymarket: https://docs.polymarket.com

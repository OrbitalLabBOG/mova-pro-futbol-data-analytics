# WhoScored Collector — la mina de oro de event data

> Validado en vivo **2026-06-28**. WhoScored publica el match centre del Mundial 2026 con **datos Opta** (1.300-1.600 eventos/partido con coordenadas) y lo bajamos **gratis, sin browser** vía CloudScraper. Esto llena el hueco que ninguna API gratis cubre (ver [02-fuentes-datos.md](02-fuentes-datos.md)).

## Por qué CloudScraper (no Playwright/soccerdata)

| Método | Resultado | Nota |
|---|---|---|
| `requests` simple | ❌ 403 | Cloudflare bloquea |
| **CloudScraper** | ✅ **200, sin browser** | Resuelve el challenge de Cloudflare. Ligero. Funciona igual en WSL y VPS. |
| Playwright headless | ❌ `require is not defined` | WhoScored detecta/oculta `require` en headless |
| soccerdata (Selenium) | ✅ pero pesado | Probado a escala (380 partidos PL) pero requiere Chrome + xvfb. Lo replicamos sin browser. |

## Dónde viven los datos

El match centre está embebido en el HTML en:
```js
require.config.params["args"] = { matchId, matchCentreData: {...}, ... };
```
`matchCentreData` trae: `events[]` (con `x, y, endX, endY, type, outcomeType, qualifiers, isShot, isGoal, playerId`), `playerIdNameDictionary`, `home/away` (lineups con `position, shirtNo, age, height, stats` por minuto: ratings, pases, posesión), `venueName`, `attendance`, `referee`, scores (`htScore, etScore, pkScore`).

**Parsing:** brace-matching string-aware (no regex frágil) + entrecomillado de las 4 claves JS top-level (`matchId, matchCentreData, matchCentreEventTypeJson, formationIdNameMappings`). Implementado en `src/mova_data/collectors/whoscored.py::_extract_args_json`.

## IDs del torneo (WhoScored)

```
Region 247 (International) · Tournament 36 (FIFA World Cup) · Season 10498 (2026)
```

Stages (descubiertos desde la página de la temporada):
| stage_id | nombre |
|---|---|
| 23753-23764 | Grupos A → L (12 grupos × 6 partidos = 72) |
| 23752 | Final Stage (R32 → Final, 32 partidos) |
| 25505 | "Grp. Stages" (agregado, **devuelve vacío** — no usar) |

## Endpoints

```
# Discovery de fixtures (JSON) — por stage y mes (YYYYMM)
GET https://www.whoscored.com/tournaments/{stage_id}/data/?d=202606
    headers: X-Requested-With: XMLHttpRequest
    → tournaments[0].matches[]  con id, status, equipos, scores, startTimeUtc, matchIsOpta

# Match centre (HTML con el JSON embebido)
GET https://www.whoscored.com/matches/{match_id}/live
```

Códigos de estado: `status=3` finalizado (FT/ET/PK), `status=1/0` programado. Solo los finalizados tienen event data.

## Arquitectura del collector

Diseño **desacoplado y pluggable** (descarga ≠ parseo ≠ modelo):

```
src/mova_data/
├── config.py                 # IDs, rutas, constantes del torneo
├── db.py                     # esquema SQLite (source-agnostic) + init/conexión
├── collectors/
│   ├── base.py               # BaseCollector ABC: discover() + fetch()
│   └── whoscored.py          # CloudScraper + discovery + parsing
└── loaders/
    └── whoscored.py          # cache JSON → SQLite (idempotente)
scripts/collect.py            # orquestador: discover → fetch → load
data/
├── raw/whoscored/{id}.json   # cache crudo por partido
└── mundial.db                # SQLite
```

**Principios:**
1. **Descarga ≠ parseo.** El raw se cachea en disco; re-parsear no re-descarga. Re-ejecutar solo baja partidos nuevos/recién finalizados.
2. **Source-agnostic.** Toda tabla de hechos lleva columna `source`. Agregar StatsBomb/API = nuevo `collector` + `loader`, sin tocar el esquema ni el modelo.
3. **Idempotente.** `UNIQUE(source, match_id, ws_event_id)` en eventos; `ON CONFLICT` en matches. Seguro re-correr.
4. **Mantener al día.** `python scripts/collect.py` en cron baja lo que falte (R16, cuartos…) conforme se juega.

## Esquema SQLite (training-ready)

`matches` (1 fila/partido: stage, round, scores, venue, referee, n_events) · `teams` · `players` · `lineups` (titular/suplente, posición, edad) · `events` (la tabla grande, ~100K+ filas, con coordenadas y qualifiers JSON).

Para entrenar: `SELECT ... FROM events JOIN matches USING(match_id)` filtrando por `is_shot`, zonas (`x,y`), tipo de evento, etc. Los `qualifiers` (JSON) contienen `endX/endY` de pases, parte del cuerpo del tiro, big chance, etc.

## Uso

```bash
python scripts/collect.py                  # discover + fetch finalizados + load
python scripts/collect.py --discover-only  # solo listar fixtures
python scripts/collect.py --limit 5        # prueba (5 partidos)
python scripts/collect.py --load-only      # recargar cache → DB
python scripts/collect.py --include-unfinished --force  # forzar re-descarga
```

## Cobertura confirmada (2026-06-28)

Discovery devolvió **88 fixtures** (72 grupos + 16 R32), **73 finalizados** (los 72 de grupos + Sudáfrica 0-0 Canadá). El resto de R32 y rondas siguientes se irán bajando solas al re-correr el collector.

## Cuidados / ToS

- WhoScored es Opta: zona gris de ToS. Uso analítico/investigación interno. **Cachear y no abusar** (delay 6s entre partidos). Para producto comercial a escala → licenciar Opta/StatsBomb.
- CloudScraper puede romperse si Cloudflare cambia el challenge. Fallback: soccerdata (Selenium+xvfb), ya probado en el stack `premier-league`.

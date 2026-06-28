# WhoScored — Diccionario de datos (Mundial 2026)

> Basado en exploración real de los **73 partidos / 112.059 eventos** cargados (2026-06-28). Documenta qué trae la fuente, su tipo, y qué cargamos hoy vs. qué queda disponible para extraer después.

## Sistema de coordenadas

Cancha normalizada **0-100 en ambos ejes** (no metros):
- `x`: 0 = línea de fondo propia, 100 = línea de fondo rival (dirección de ataque del equipo en posesión).
- `y`: 0 = banda derecha, 100 = banda izquierda (vista del equipo atacante).
- Portería rival centrada en `x=100, y=50`. Para tiros, `GoalMouthY` (0-100 horizontal del arco) y `GoalMouthZ` (altura) describen dónde fue el remate.
- Verificado: todos los `x, y, endX, endY` ∈ [0, 100].

---

## 1. Estructura del JSON crudo

Top-level del archivo cacheado (`data/raw/whoscored/{match_id}.json`):

| Campo | Tipo | Descripción |
|---|---|---|
| `matchId` | int | ID del partido en WhoScored |
| `matchCentreData` | dict | **Todo el dato del partido** (ver §2) |
| `matchCentreEventTypeJson` | dict | Mapa nombre→id de ~200 tipos de stat de tiro/evento (ej. `shotPenaltyArea:1`) |
| `formationIdNameMappings` | dict | id de formación → nombre (ej. `"4":"433"`, `"2":"442"`) |

### `matchCentreData` (dict principal)

| Campo | Tipo | Notas |
|---|---|---|
| `events` | list | **Lista de eventos** del partido (~1.300-1.640). Ver §3 |
| `home` / `away` | dict | Bloque por equipo: lineups, stats, formaciones, incidencias. Ver §6 |
| `playerIdNameDictionary` | dict | `playerId(str) → nombre` |
| `score` / `htScore` / `ftScore` / `etScore` / `pkScore` | str | Marcadores `"0 : 0"` (et/pk vacíos si no aplica) |
| `venueName` | str | Estadio |
| `attendance` | int | Asistencia |
| `referee` | dict | `officialId, firstName, lastName, name` |
| `weatherCode` | str | Código de clima (a menudo vacío) |
| `elapsed` | str | `"FT"`, `"HT"`, minuto en vivo |
| `startTime` / `startDate` | str | ISO local |
| `statusCode` / `periodCode` | int | Estado interno (6 = finalizado) |
| `maxMinute` / `minuteExpanded` / `maxPeriod` | int | Límites temporales |
| `periodMinuteLimits` / `expandedMinutes` / `periodEndMinutes` | dict | Mapeo minuto real ↔ expandido (descuento) |
| `commonEvents` | list | Normalmente vacío |
| `timeoutInSeconds` | int | 300 |

---

## 2. EVENTOS — campos (tabla `events`)

Cada evento (validado sobre 112K filas). Tipos observados entre llaves:

| Campo | Tipo | SQLite | Descripción |
|---|---|---|---|
| `id` | float | REAL | ID único global del evento (Opta), grande |
| `eventId` | int | INTEGER | ID secuencial dentro del partido |
| `minute` | int | INTEGER | Minuto de juego |
| `second` | int | INTEGER | Segundo (a veces null) |
| `expandedMinute` | int | INTEGER | Minuto continuo incluyendo descuento |
| `period` | dict→str | TEXT | `FirstHalf, SecondHalf, FirstPeriodOfExtraTime, PreMatch, PostGame` |
| `type` | dict→str | TEXT (`event_type`) | Tipo de acción (39 valores, §4) |
| `outcomeType` | dict→str | TEXT (`outcome`) | `Successful` / `Unsuccessful` |
| `teamId` | int | INTEGER | Equipo que ejecuta |
| `playerId` | int | INTEGER | Jugador (null en eventos de sistema: Start/End/Formation) |
| `x`, `y` | float | REAL | Posición inicio (0-100) |
| `endX`, `endY` | float | REAL | Posición fin (pases/conducciones; 1081/1488 eventos los tienen) |
| `goalMouthY`, `goalMouthZ` | float | REAL | Solo tiros: ubicación en el arco |
| `blockedX`, `blockedY` | float | REAL | Solo tiros bloqueados: punto del bloqueo |
| `isTouch` | bool | INTEGER | Si implicó contacto con balón |
| `isShot` | bool | INTEGER | Marca de tiro (≈37/partido) |
| `isGoal` | bool | INTEGER | Marca de gol |
| `cardType` | dict→str | TEXT | Tipo de tarjeta (solo eventos Card) |
| `relatedEventId` | int | INTEGER | Vincula eventos (ej. tiro↔asistencia) |
| `relatedPlayerId` | int | INTEGER | Jugador relacionado |
| `qualifiers` | list | TEXT (JSON) | **Detalle fino del evento** (§5) |
| `satisfiedEventsTypes` | list | (no cargado) | IDs de métricas que el evento satisface (cruzar con `matchCentreEventTypeJson`) |

> Distribución temporal: ~55.8K eventos 1er tiempo, ~56K 2do, ~290 PreMatch/PostGame.
> Outcomes: 89.400 Successful / 22.659 Unsuccessful.

---

## 3. Ejemplos

**Pase** (con geometría en qualifiers):
```
type=Pass outcome=Successful x=50 y=50 endX=37.3 endY=42.2
qualifiers: Zone=Back, PassEndX=37.3, PassEndY=42.2, Length=14.4, Angle=3.52
```
**Tiro atajado** (con detalle de remate):
```
type=SavedShot isShot=true x=86.7 y=69.4 relatedPlayerId=322655 (asistente)
qualifiers: RightFoot, RegularPlay, Assisted, Zone=Center, BoxLeft, LowLeft,
            Blocked, GoalMouthY=52.6, GoalMouthZ=...
```

---

## 4. Catálogo de tipos de evento (39, toda la DB)

| Tipo | n | | Tipo | n |
|---|--:|---|---|--:|
| Pass | 72.715 | | OffsideGiven/Pass/Provoked | 249 c/u |
| BallRecovery | 5.581 | | **Goal** | **215** |
| BallTouch | 4.802 | | Card | 191 |
| Aerial | 3.800 | | Error | 159 |
| Clearance | 3.595 | | FormationSet | 146 |
| Foul | 3.253 | | ShieldBallOpp | 100 |
| TakeOn (regate) | 2.694 | | KeeperSweeper | 93 |
| Tackle | 2.352 | | Claim | 90 |
| CornerAwarded | 1.270 | | Punch | 69 |
| Interception | 1.234 | | **ShotOnPost** | 28 |
| Dispossessed | 1.214 | | Smother | 25 |
| Challenge | 1.079 | | PenaltyFaced | 11 |
| BlockedPass | 1.012 | | ChanceMissed | 10 |
| **SavedShot** | 858 | | GoodSkill | 10 |
| Save | 856 | | CrossNotClaimed | 3 |
| KeeperPickup | 754 | | | |
| **MissedShots** | 703 | | | |
| Substitution On/Off | 693 c/u | | | |

> **Tiros** = SavedShot + MissedShots + ShotOnPost + Goal (+ qualifiers de bloqueo). `is_shot=1` ≈ 1.804 filas.

---

## 5. Qualifiers (111 tipos distintos)

Cada qualifier es `{type:{value:int, displayName:str}, value?:str}`. Guardados como JSON en `events.qualifiers`. Los más relevantes:

**Geometría de pase** — `PassEndX(140)`, `PassEndY(141)`, `Length(212)`, `Angle(213)`, `Zone(56)`, `Cross(2)`, `Longball(1)`, `Chipped(155)`, `HeadPass(3)`, `ThrowIn(107)`, `Corner Taken(6)`, `Freekick Taken(5)`.

**Detalle de tiro** — `GoalMouthY(102)`, `GoalMouthZ(103)`, `RightFoot(20)`, `LeftFoot(72)`, `Head(15)`, `RegularPlay(22)`, `Blocked(82)`, `BlockedX/Y(146/147)`, `BoxCentre(17)`, `OutOfBoxCentre(18)`, posiciones de arco (`LowLeft/LowCentre/MissHigh/MissLeft`…), `BigChance`, `IndividualPlay(215)`.

**Creación de juego** — `KeyPass(11113)`, `Assisted(29)`, `IntentionalAssist(154)`, `ShotAssist(210)`, `LayOff(156)`, `RelatedEventId(55)`, `OppositeRelatedEvent(233)`.

**Contexto** — `Offensive(286)`, `Defensive(285)`, `FirstTouch(328)`, `PlayerPosition(44)`, `JerseyNumber(59)`, `FormationSlot(145)`.

> El cruce `Zone(56)` + `PassEndX/Y` + `Length/Angle` permite reconstruir **redes de pases y mapas de progresión**. Los qualifiers de tiro permiten **entrenar nuestro propio xG** (WhoScored no entrega xG directo).

---

## 6. Bloque por equipo (`home`/`away`) — disponible, parcialmente cargado

| Campo | Tipo | ¿Cargado? | Contenido |
|---|---|---|---|
| `teamId`, `name`, `countryName` | int/str | ✅ (teams) | Identidad |
| `players` | list | ✅ (lineups) | Ver §7 |
| `managerName` | str | ⬜ | DT |
| `averageAge` | float | ⬜ | Edad promedio |
| `formations` | list | ⬜ | **Timeline de formaciones**: `formationId/Name, captainPlayerId, startMinute/endMinuteExpanded, playerIds, formationSlots, formationPositions` |
| `stats` | dict | ⬜ | **Series por minuto** a nivel equipo: `shotsTotal, shotsOnTarget, possession, passesTotal/Accurate/Key, aerialsWon, corners, tackles, dribbles, errors`… (cada uno `{minuto: valor}`) |
| `shotZones` | dict | ⬜ | Tiros agregados por zona |
| `incidentEvents` | list | ⬜ | Eventos clave (goles, cambios, tarjetas) ya filtrados |
| `scores` | dict | ⬜ | Marcador por periodo |

## 7. Jugador (tabla `lineups`)

| Campo | Tipo | ¿Cargado? |
|---|---|---|
| `playerId`, `name`, `shirtNo`, `position` | int/str | ✅ |
| `isFirstEleven`, `isManOfTheMatch` | bool | ✅ |
| `age`, `height` | int | ✅ |
| `weight` | int | ⬜ |
| `subbedInPlayerId`, `subbedOutPeriod`, `subbedOutExpandedMinute` | — | ⬜ (cambios) |
| `stats` | dict | ⬜ | **Series por minuto** por jugador: `ratings, possession, touches, passesTotal/Accurate/Key, passSuccess, tackles, interceptions, clearances, dribbledPast, fouls`… |

---

## 8. Mapeo a nuestra DB (`data/mundial.db`)

| Tabla | Filas (2026-06-28) | Fuente |
|---|--:|---|
| `matches` | 88 (73 con eventos) | discovery + match centre |
| `events` | 112.059 | `matchCentreData.events` |
| `lineups` | 3.743 | `home/away.players` |
| `players` | 1.247 | `playerIdNameDictionary` |
| `teams` | 48 | `home/away` |

Tipos SQLite: IDs y flags `INTEGER` (bool→0/1), coordenadas/`id` de evento `REAL`, textos/JSON `TEXT`. Toda tabla de hechos lleva `source` (hoy `'whoscored'`).

## 9. Pendiente de extraer (alto valor, ya disponible en el crudo)

1. **Series por minuto** equipo y jugador (`stats`) → momentum, xG acumulado, ratings.
2. **Formaciones con timeline** → contexto táctico, cambios de esquema.
3. **`shotZones`** y **`satisfiedEventsTypes`** (cruzar con `matchCentreEventTypeJson`).
4. **Cambios** (`subbedIn/Out`) y `incidentEvents` como tabla aparte.
5. **xG propio** desde qualifiers de tiro (no viene dado).

> Todo esto ya está en `data/raw/whoscored/*.json` cacheado: extraerlo no requiere re-scrapear, solo ampliar el loader.

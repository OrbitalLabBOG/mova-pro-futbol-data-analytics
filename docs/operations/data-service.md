---
type: runbook
name: "MOVA FPL — servicio autónomo de datos"
created: 2026-08-23
updated: 2026-08-24
tags: [mova, fpl, collector, postgres, whoscored, odds, observability]
status: active
---

# Servicio autónomo de datos

El data service recolecta y califica las fuentes que alimentan el harness sin modificar la
cuenta FPL. Corre cada 15 minutos, pero cada adapter mantiene su propio cursor y cadencia; un
fallo no impide que las demás fuentes avancen.

## Fuentes y cadencias

| Adapter | Contenido | Cadencia normal | Gate principal |
| --- | --- | ---: | --- |
| `fpl_official` | bootstrap, 380 fixtures, perfil/historia/picks y `event/{gw}/live` de GWs revisadas | 6 h | 20 clubes, 38 GWs, 500–800 jugadores, 380 fixtures |
| `market_odds` | próximas fechas EPL, `h2h` y totales por bookmaker | adaptativa 24/12/6 h + checkpoint | eventos vigentes, ≥5 casas, cobertura `h2h=1`, totales y cuota observable |
| `whoscored_schedule` | 380 IDs y estado de partidos | 24 h | 380 IDs únicos |
| `whoscored_events` | evento a evento de partidos finalizados | 30 min | status 6, 1.000–2.500 eventos, par `(id,eventId)` único |

El batch WhoScored está limitado a 10 partidos por corrida. El siguiente tick continúa el
backlog. Reutilizar `id` dentro de un partido es válido si `eventId` es distinto; la clave en
PostgreSQL es `(ws_match_id, ws_event_id, event_id)`.

`market_odds` usa The Odds API en plan gratuito. El planner lee el siguiente deadline desde
`analytics.fpl_event_observations`; no consulta si no existe un deadline futuro. A más de 72 h
muestrea cada 24 h, entre 72–24 h cada 12 h y entre 24–6 h cada 6 h, siempre con región `uk` y
mercados `h2h,totals` (2 créditos). En las últimas 6 h toma una sola observación ampliada
`uk,eu` (4 créditos). La estimación normal es ~110–120 créditos/mes, no 372.

Los headers `used`, `remaining` y `last_cost` son la autoridad del presupuesto. Por debajo de
150 créditos solo se consulta dentro de 24 h del deadline; por debajo de 75, únicamente en la
última hora. Cuota insuficiente bloquea incluso `--force`. El reset del proveedor se detecta por
el aumento de `remaining`, sin calendario local. La decisión completa queda en
`quality.policy`, logs, manifests y `/api/v1/data`; `mova_data_odds_quota_*` expone el saldo.
El histórico gratuito se construye desde nuestros snapshots; el endpoint histórico comercial
del proveedor no forma parte de este contrato.

El adapter anterior de `football-data.co.uk` queda como histórico legado. Sus filas, si existen,
permanecen en `analytics.match_odds_observations`, pero ya no es una fuente live ni mantiene un
cursor de salud.

## Operación

```bash
mova collect all
mova data status
mova data coverage
mova status --json
mova doctor --json

# Replay excepcional: no evita locks, validaciones ni deduplicación
mova collect events --force --actor julian --reason "replay de cobertura" \
  --idempotency-key "events:replay:2026-08-23"

systemctl status mova-fpl-collector.timer
journalctl -u mova-fpl-collector.service -n 200 --no-pager
curl -s http://127.0.0.1:8787/api/v1/data | python -m json.tool
curl -s http://127.0.0.1:8787/api/v1/data/coverage | python -m json.tool
curl -s http://127.0.0.1:8787/metrics | grep '^mova_data_'
```

`collect` devuelve 0 si todas las fuentes ejecutadas están sanas, 2 si la corrida terminó con
alguna fuente degradada y 75 si otro collector conserva el lock. systemd acepta 2 y 75 como
terminación conocida; la condición continúa visible en PostgreSQL, incidentes, outbox, status,
doctor, métricas y journald.

## Persistencia y trazabilidad

Los bytes viven bajo
`/var/lib/mova-fpl/artifacts/data-service/raw/<source>/<season>/<observed_at>/`. Cada directorio
incluye `manifest.json`, SHA-256, timestamp, método, calidad y conteos. La publicación es atómica;
un hash ya registrado no vuelve a cargar filas.

PostgreSQL conserva:

- `raw.ingestion_runs`, `raw.source_cursors`, `raw.source_artifacts` y `raw.quality_checks`;
- observaciones FPL en `analytics.fpl_team_observations`,
  `analytics.fpl_event_observations`, `analytics.fpl_player_observations` y
  `analytics.fpl_fixture_observations`; los puntos, minutos, componentes y `explain`
  oficiales por GW quedan en `analytics.fpl_event_live_observations`;
- perfil/historia/picks públicos en `game.fpl_entry_observations` y
  `game.fpl_pick_observations`;
- snapshots completos de mercado en `analytics.market_odds_observations`; el CSV legado queda
  en `analytics.match_odds_observations`;
- calendario, partidos y eventos en `analytics.whoscored_*`;
- salud derivada en `ops.v_data_source_health`.

La clave de The Odds API vive en `/etc/mova-fpl/odds-api-key` (`root:10001`, `0640`) y Docker
la monta solamente en el worker como `/run/secrets/odds_api_key`. No vive en `runtime.env`, Git,
manifests ni PostgreSQL. Los logs no contienen payloads: registran tamaños, hashes, filas,
duración, job, step y
correlation id. Los JSON completos se consultan por artifact ref. Cookies, credenciales, HTML
autenticado y secretos no entran en esta capa.

## Diagnóstico

1. Ejecutar `mova data status` y ubicar `health`, `age_seconds`, `consecutive_failures` y el
   último `error_code`.
2. Consultar el `job_id` en `/api/v1/jobs` y sus pasos en `/api/v1/steps`.
3. Revisar el incidente deduplicado y el manifest del último éxito; no borrar evidencia.
4. Reintentar solo la fuente afectada con actor, razón e idempotency key.
5. Para WhoScored, separar `schedule` de `events`: el calendario vivo consulta cada mes y los
   partidos se descargan y validan individualmente usando la cache resultante.

Una fuente se recupera cuando una corrida validada actualiza su cursor; el incidente homónimo se
cierra automáticamente. Tras un fallo, el próximo intento respeta la cadencia desde
`last_attempt_at`; el timer de 15 minutos evalúa, pero no martilla el proveedor. Un adapter
degradado no autoriza usar datos stale para ejecutar cambios en FPL.

## Deploy y rollback

El engine instala Chromium y Playwright. El collector consulta directamente `wsCalendar` y los
endpoints mensuales de WhoScored desde un Chromium headless efímero, sin Selenium, Xvfb ni
`soccerdata`. No monta el perfil autenticado; el browser persistente de FPL continúa aislado.

Antes del deploy: backup/restore drill vigente, tests, `docker compose config`, migraciones
PostgreSQL hasta `005` y una corrida validada por fuente. Para rollback, deshabilitar el timer,
volver al checkout/imagen anterior y conservar las migraciones: son aditivas y no alteran el path
de decisión.
Los dumps diarios de PostgreSQL incluyen filas normalizadas; los artefactos raw permanecen en el
volumen del VPS.

---
type: evidence
name: "HV1-03a — Servicio autónomo de datos"
created: 2026-08-23
updated: 2026-08-23
tags: [mova, fpl, hv1-03, collector, data-quality, whoscored, odds]
status: deployed-shadow
---

# Evidencia HV1-03a — Servicio autónomo de datos

## Alcance

Este corte convierte FPL oficial, odds, calendario WhoScored y eventos WhoScored en
adapters independientes, persistentes y observables. El servicio recolecta y califica
datos; no entrena modelos, decide alineaciones ni escribe en la cuenta FPL.

La interfaz uniforme de modelos permanece como **HV1-03b**. Esta separación evita declarar
completo un contrato analítico que todavía no tiene evidencia de release, inferencia y
scorecard reproducibles.

## Release

| Campo | Valor |
| --- | --- |
| Revisión desplegada | `52acb403dd4f9c16da0e90b1ae6012d57ad75d21` |
| Imagen | `mova-fpl-engine:52acb40` |
| Migración | PostgreSQL `003` |
| Pull requests | `#9` data service, `#10` backoff, `#11` cache de build, `#13` odds live |
| Runtime | `/opt/orbital/services/mova-fpl` |
| Estado | `healthy`: cuatro fuentes activas y sin warnings |

## Contrato entregado

- cuatro adapters con cursor, cadencia, lock e idempotencia propios;
- artifact raw inmutable, manifest, hash SHA-256 y publicación atómica;
- runs, quality checks, filas normalizadas, jobs, steps, incidentes y outbox en PostgreSQL;
- CLI `mova collect`, `mova data status|coverage` y replay forzado auditable;
- `/api/v1/data`, health derivado y métricas Prometheus `mova_data_*`;
- timer systemd cada 15 minutos con cadencias por fuente;
- fallos aislados: una fuente degradada no bloquea las demás;
- logs JSON correlacionados en journald sin payloads ni secretos;
- runbook y skill de operación actualizados.

## Evidencia de datos vivos

Corridas forzadas verificadas en el VPS el 2026-08-24 UTC:

| Fuente | Resultado | Calidad / volumen | Duración |
| --- | --- | --- | ---: |
| FPL oficial | healthy | 609 jugadores, 380 fixtures, 20 equipos, 38 GWs, entry `3609854`, 15 picks de GW1 | 1,65 s |
| WhoScored schedule | healthy | 380 IDs únicos, 9 partidos finalizados | 14,16 s |
| WhoScored events | healthy | 9/9 partidos, 13.744 eventos, cobertura `1.0`, 0 fallos | 75,75 s |
| The Odds API | healthy | 21 partidos, 43 casas, 2.395 líneas; `h2h` y totales con cobertura `1.0` | 1,60 s |

El partido de integración `1983546` produjo 1.495 eventos válidos dentro de un contenedor
sin privilegios, con todas las capabilities removidas. PostgreSQL conserva 13.744 eventos
con clave compuesta `(ws_match_id, ws_event_id, event_id)`.

El adapter live de `football-data.co.uk` fue retirado sin borrar su evidencia. The Odds API
conserva cada bookmaker, mercado, outcome y línea en
`analytics.market_odds_observations`: 1.905 filas `h2h` de 43 casas y 490 de totales de 20 casas.
La primera consulta costó 4 créditos; el saldo observado quedó en 492 de 500.

## Autonomía y observabilidad

| Check | Resultado |
| --- | --- |
| Timer | activo y habilitado; evalúa cada 15 min |
| Cadencia FPL / odds | 6 h / adaptativa 24–12–6 h + checkpoint final |
| Cadencia schedule / events | 24 h / 30 min |
| Batch de eventos | máximo 10 partidos por corrida; backlog reanudable |
| Cuota odds | 2 créditos normales, 4 en un checkpoint pre-deadline; ~110–120/mes, reservas 150/75 |
| API | `/healthz`, `/api/v1/data` y `/metrics` responden `200` |
| Doctor | 20 PASS, 0 WARN, 0 FAIL, 0 required failures |
| Repositorio VPS | limpio en `52acb40` |
| Contenedor API | running y healthy |
| Disco | 37 GiB libres, 62 % usado |

La corrida natural de las 01:45 UTC evaluó las cuatro fuentes y terminó en `completed`:
todas fueron `skipped/cadence_not_due`. Esto prueba que el timer observa frecuentemente sin
repetir descargas ni martillar una fuente fallida.

## Verificación y recuperación

| Check | Resultado |
| --- | --- |
| Suite hermética final | `733 passed, 1 skipped, 79 deselected` |
| CI | verde en los tres pull requests del corte |
| Compose | configuración válida |
| Dedupe FPL | segunda carga idéntica insertó 0 filas nuevas |
| Integración PostgreSQL | FPL, odds fixture, schedule y 1.000 eventos cargados y consultados |
| Backup SQLite | `/opt/orbital/backups/mova-fpl/20260824T012817Z` |
| Backup PostgreSQL pre-migración | `/opt/orbital/backups/mova-fpl/postgres/20260824T030047Z` |
| Restore drill | dump restaurado y verificado en base temporal; base eliminada al finalizar |

Las migraciones `002` y `003` son aditivas. El rollback consiste en detener el timer, volver a la imagen
anterior y conservar tanto las tablas como los artefactos capturados para auditoría.

## Gates conservados

- `mode=shadow`, `action_level=A0` y browser writes deshabilitados;
- ninguna transferencia, chip, capitán o cambio de plantilla ejecutado;
- Supabase permanece fuera de la operativa y solo refleja seguimiento PM;
- datos stale o missing pueden informar un análisis declarado, nunca una ejecución.

## Estado siguiente

WP-003 y HV1-03a quedan completos. Permanecen abiertos:

1. HV1-03b: contrato uniforme `train/predict/explain/evaluate` y releases de modelos;
2. HV1-04: estado de equipo y memoria estratégica sobre el store durable.

---
type: workpack
name: "WP-002 — Control plane SQLite y scheduler"
created: 2026-08-21
updated: 2026-08-31
tags: [mova, fpl, workpack, sqlite, scheduler]
status: active-shadow
---

# WP-002 — Control plane SQLite y scheduler

## Objetivo

Implementar `ops.db`, state machine, jobs, locks, gates, kill switches y outbox local.

## Dependencias

WP-001 para integración; el DDL/migration runner puede prepararse antes sin desplegarse.

## Entregables

- migraciones SQLite versionadas con checksum y rollback compatible;
- WAL con SQLite ≥3.51.3, foreign keys, busy timeout, permisos y single-writer;
- `tick`, `flock`, idempotency y compare-and-set;
- CLI/API de pause, resume, mode y kill switch con auditoría;
- outbox con retry y acuse.

## Criterios de aceptación

- `quick_check`, foreign key check e índices esperados pasan;
- un test concurrente writer/reader/checkpoint pasa con la versión SQLite fijada;
- backup y restore usan la imagen engine, nunca `/usr/bin/sqlite3` del host;
- `ops.db` no tiene listener de red y solo el usuario/containers MOVA acceden al path;
- dos ticks concurrentes producen un solo job lógico;
- caída entre claim y persistencia se recupera sin duplicar;
- ninguna llamada externa ocurre dentro de transacción;
- cambios de gate/mode quedan en audit trail.

## Rollback

Desactivar timer, preservar `ops.db`/WAL, restaurar imagen y migration compatible anterior.

## Estado verificado

El control plane SQLite, migraciones, WAL, jobs idempotentes, gates, auditoría, backup y
scheduler están desplegados en shadow. El outbox ahora tiene claim con lease recuperable,
entrega local a journald fuera de la transacción, retry exponencial, estado `dead` tras cinco
intentos y acuse idempotente por CLI. El watchdog despacha alertas vencidas en cada corrida.
Permanece `active-shadow` hasta completar los gates de migración del writer y seleccionar, si
se requiere notificación fuera del VPS, un canal externo con credenciales y owner explícitos.

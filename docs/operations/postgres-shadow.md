---
type: runbook
name: "MOVA FPL — PostgreSQL shadow"
created: 2026-08-23
updated: 2026-08-30
tags: [mova, fpl, postgres, migration, backup, restore]
status: active-shadow
---

# PostgreSQL shadow

HV1-02 instala PostgreSQL como candidato durable sin cambiar todavía la autoridad del runtime.
SQLite continúa siendo el único writer; PostgreSQL recibe imports programados, verificables e
idempotentes. El adapter dual-read ya compara contenido normalizado. El cutover del writer y el
retiro de SQLite siguen fuera de esta fase.

## Contrato de seguridad

- imagen fijada a PostgreSQL 17.11 Bookworm por digest `amd64`;
- red Docker `data` interna, sin puerto publicado en el host;
- secreto en `/etc/mova-fpl/postgres-password`, `root:10001` y `0640`: root lo entrega al
  contenedor PostgreSQL y el grupo del worker puede leerlo; nunca entra en Git ni stdout;
- `mova_owner` aplica migraciones/imports; los roles `mova_app` y `mova_readonly` son grupos
  `NOLOGIN` con mínimos privilegios;
- migraciones SQL inmutables con checksum y advisory lock;
- import bajo una transacción y un segundo advisory lock;
- cada import exige actor, razón y clave de idempotencia;
- la fuente son snapshots consistentes creados con SQLite Online Backup API, no copias de
  archivos vivos con WAL;
- los artefactos fuente conservan SHA-256, manifest y `quick_check`.

## Modelo de datos

| Schema | Propósito |
| --- | --- |
| `mova_meta` | migraciones, import runs y checks |
| `raw` | snapshots de fuentes |
| `analytics` | histórico canónico, datasets, modelos y proyecciones |
| `game` | temporadas, ciclos y estado del equipo |
| `research` | señales con evidencia |
| `agent` | decisiones, estrategia, ejecución y traza legacy |
| `ops` | controles, jobs, salud, auditoría, incidentes y outbox |

`analytics.player_gameweek.source_row_id` conserva el `rowid` SQLite como PK. No se impone
una unicidad artificial a `(season, gw, player_key, fixture)`: el histórico real contiene
duplicados y deben investigarse en la capa de calidad, no perderse durante la migración.

## Inicializar e importar

Desde el checkout aprobado del VPS:

```bash
sudo deploy/bin/bootstrap-host.sh
set -a; source /etc/mova-fpl/deploy.env; set +a
docker compose up -d --wait postgres
mova postgres migrate
mova postgres import \
  --actor julian \
  --reason "HV1-02a shadow baseline" \
  --idempotency-key "hv1-02a:baseline:<git-sha>"
mova postgres status
mova postgres verify
mova postgres sync
mova postgres drill \
  --actor codex \
  --reason "ensayo read-path antes del cutover" \
  --idempotency-key "2026-27-gw03:read-cutover-v1"
mova postgres roles \
  --actor codex \
  --reason "provisión least-privilege" \
  --idempotency-key "2026-27-gw03:roles-v1"
```

`import` trunca y reconstruye únicamente las tablas shadow declaradas. No modifica las tres
bases SQLite. Repetir la misma clave devuelve `reused`; para una nueva fotografía se usa una
clave nueva y descriptiva.

`verify` exige un import completado, recalcula hashes/`quick_check` de sus snapshots y vuelve a
leer SQLite y PostgreSQL. Compara filas normalizadas y SHA-256 exactos en las tablas operativas;
para el histórico canónico grande usa invariantes agregados deterministas. No exige que las
SQLite vivas sigan iguales: el import representa deliberadamente un punto en el tiempo.

`sync` deriva una clave `postgres-shadow-sync:<cycle>:<semana ISO>` del ciclo vigente. El timer
lo invoca diariamente, pero solo crea un import por ciclo y semana; las repeticiones devuelven
`reused`. El service comparte el lock de workers y deja un resumen compacto en journald.

## Drill de cutover/rollback de lectura

`postgres drill` no cambia configuración ni writer. Parte del snapshot SQLite inmutable del
último import verificado, relee siete contratos críticos —controles, ciclo, equipo, research,
envelope, execution plan y rehearsals— desde PostgreSQL y finalmente vuelve a leerlos desde
SQLite. La secuencia finita es:

```text
sqlite_baseline → postgres_candidate → sqlite_rollback
```

Cada paso conserva conteo y SHA-256. Drift o indisponibilidad del candidato fallan el job; el
rollback se ejecuta en `finally` y sólo figura verificado si el hash SQLite posterior reproduce
el baseline. La operación exige actor, razón y clave idempotente; reutilizar la clave con otra
identidad se rechaza. La evidencia queda en `artifacts/postgres-cutover-drills/`, los jobs/audit
en SQLite y la superficie read-only en `/api/v1/postgres-cutover-drills`. Prometheus expone
`mova_postgres_cutover_drill_status` y `mova_postgres_cutover_rollback_verified`.

Este drill cubre la revisión candidata del **read-path** sin dual-write. No autoriza el cutover
del writer, no convierte PostgreSQL en fuente operativa y no sustituye los gates multi-GW,
off-host o aprobación explícita.

## Identidades runtime separadas

`postgres roles` usa el owner exclusivamente para rotar las contraseñas de
`mova_app_runtime` y `mova_readonly_runtime`. Los secretos viven en archivos Docker distintos,
con permisos `root:10001 0640`, y nunca forman parte del job, artifact, API ni log. La identidad
app hereda `SELECT/INSERT/UPDATE`, sin `DELETE` ni `TEMP`; readonly hereda sólo `SELECT`, no tiene
`TEMP` y arranca con `default_transaction_read_only=on`. Ambas tienen límites de conexión y
timeouts defensivos.

La operación exige actor, razón y llave idempotente. Verifica conexiones reales, membresías y
privilegios efectivos; sella el resultado bajo `artifacts/postgres-role-provision/`. El drill de
cutover usa readonly para todo acceso candidato. `mova postgres status`, API y Prometheus exponen
el estado sanitizado `role_separation`/`mova_postgres_role_separation_status`.

## Estado observable sin ampliar autoridad

El worker publica después de cada import/verify un artefacto sanitizado en
`artifacts/postgres-shadow-status.json`. La API monta solo ese archivo: no recibe password,
conectividad a la red `data` ni privilegios PostgreSQL. `/api/v1/status.storage` y Prometheus
exponen rol, último import, edad, migration count y paridad. El estado se degrada si falta el
artefacto, la paridad falla o tiene más de ocho días.

## Backup y restauración

El timer diario ejecuta `deploy/bin/backup-all.sh`: primero el backup SQLite existente y luego
un dump PostgreSQL custom, listado con `pg_restore` y manifest SHA-256. Retención local: 35 días.

```bash
backup_dir="$(sudo deploy/bin/postgres-shadow-backup.sh)"
sudo deploy/bin/postgres-shadow-restore-drill.sh "$backup_dir"
```

El drill verifica el hash, crea una base temporal con prefijo validado `mova_restore_`, restaura
con `--exit-on-error`, valida los siete schemas y tablas núcleo, y siempre elimina solo esa base
temporal. Nunca restaura encima de `mova`.

## Diagnóstico y rollback

```bash
mova postgres status
mova postgres verify
docker compose ps postgres
docker compose logs --tail=100 postgres
```

Para probar indisponibilidad y recuperación reales sin improvisar stops:

```bash
sudo deploy/bin/postgres-recovery-drill.sh \
  codex "chaos PostgreSQL shadow" "hv1-09d-live-YYYYMMDD"
```

El host toma todos los locks de writers, verifica paridad, detiene sólo PostgreSQL, prueba que el
cliente falle mientras API y SQLite siguen disponibles, recupera la misma imagen y vuelve a
validar 54 contratos. La evidencia se importa como `postgres_recovery`; repetir la identidad
completada no provoca otra caída. Un exit 75 difiere el ensayo porque existe un writer activo.

Ante fallo, detener nuevos imports y conservar el artefacto fallido. Como SQLite sigue siendo
writer, el rollback operativo es deshabilitar `mova-fpl-postgres-sync.timer` y detener
`postgres`; collector, modelos y decisiones continúan leyendo SQLite. La API declarará el shadow
no disponible en vez de ocultarlo. No borrar `/var/lib/mova-fpl/postgres` ni restaurar sobre la
base activa sin un cambio aprobado.

## Gates pendientes para cutover

1. acumular imports y comparaciones independientes durante al menos tres ciclos;
2. ~~identidades LOGIN separadas para app y lectura~~ — cubierto y usado por el drill;
3. backup off-host cifrado, sujeto a aprobación Q-04 del destino;
4. aprobación explícita del cambio de writer;
5. ~~ensayo de cutover y rollback de lectura de la revisión candidata~~ — cubierto por el drill.

El writer real sólo se cambia después de los tres gates todavía abiertos.

El repository dual-read, la paridad, roles runtime, restore drill local y cutover/rollback de
lectura ya están cubiertos. No se consideran evidencia suficiente para cambiar el writer antes de
los gates restantes.

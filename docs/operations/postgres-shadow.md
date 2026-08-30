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

Ante fallo, detener nuevos imports y conservar el artefacto fallido. Como SQLite sigue siendo
writer, el rollback operativo es deshabilitar `mova-fpl-postgres-sync.timer` y detener
`postgres`; collector, modelos y decisiones continúan leyendo SQLite. La API declarará el shadow
no disponible en vez de ocultarlo. No borrar `/var/lib/mova-fpl/postgres` ni restaurar sobre la
base activa sin un cambio aprobado.

## Gates pendientes para cutover

1. acumular imports y comparaciones independientes durante al menos tres ciclos;
2. credenciales LOGIN separadas para app y lectura;
3. backup off-host cifrado;
4. aprobación explícita del cambio de writer;
5. ensayo de cutover y rollback de la revisión candidata.

El repository dual-read, la paridad de contenido y el restore drill local ya están cubiertos. No
se consideran evidencia suficiente para cambiar el writer antes de los gates restantes.

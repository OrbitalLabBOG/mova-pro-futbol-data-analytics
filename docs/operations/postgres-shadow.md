---
type: runbook
name: "MOVA FPL — PostgreSQL shadow"
created: 2026-08-23
updated: 2026-08-23
tags: [mova, fpl, postgres, migration, backup, restore]
status: active-shadow
---

# PostgreSQL shadow

HV1-02a instala PostgreSQL como candidato durable sin cambiar la autoridad del runtime.
SQLite continúa siendo el único writer; PostgreSQL recibe imports puntuales, verificables e
idempotentes. El cutover, dual-read y retiro de SQLite no forman parte de esta fase.

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
```

`import` trunca y reconstruye únicamente las tablas shadow declaradas. No modifica las tres
bases SQLite. Repetir la misma clave devuelve `reused`; para una nueva fotografía se usa una
clave nueva y descriptiva.

`verify` exige un import completado, recalcula hashes/`quick_check` de sus snapshots y compara
los conteos PostgreSQL con los registrados. No exige que las SQLite vivas sigan iguales: el
import representa deliberadamente un punto en el tiempo.

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
writer, el rollback operativo es detener `postgres`; API, collector, modelos y decisiones no
dependen aún de él. No borrar `/var/lib/mova-fpl/postgres` ni restaurar sobre la base activa sin
un cambio aprobado.

## Gates pendientes para cutover

1. imports repetidos y comparación de queries/decisiones durante al menos tres ciclos;
2. repository adapter y dual-read explícitos;
3. credenciales LOGIN separadas para app y lectura;
4. backup off-host cifrado;
5. restore drill de la revisión candidata;
6. aprobación del cambio de writer y rollback ensayado.
